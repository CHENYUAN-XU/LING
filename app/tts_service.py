from __future__ import annotations

import io
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from typing import Any

from .voice import load_voice_config, voice_enabled
from .speech_planner import build_tts_request_params, split_reply_into_utterances


_LAST_TTS_ERROR: str | None = None
OPENAI_TTS_ENDPOINT = "https://api.openai.com/v1/audio/speech"
OPENAI_TTS_FORMATS = {"mp3", "opus", "aac", "flac", "wav", "pcm"}
LOCAL_HTTP_TTS_FORMATS = {"mp3", "wav"}
OPENAI_TTS_BUILTIN_VOICES = {
    "alloy",
    "ash",
    "ballad",
    "cedar",
    "coral",
    "echo",
    "fable",
    "marin",
    "nova",
    "onyx",
    "sage",
    "shimmer",
    "verse",
}
OPENAI_TTS_STYLE_INSTRUCTIONS = {
    "cheerful": "Speak with a warm, lightly upbeat tone.",
    "concerned": "Speak gently, with quiet concern.",
    "gentle": "Speak softly and calmly.",
}


def _set_tts_error(error: str | None) -> None:
    global _LAST_TTS_ERROR
    _LAST_TTS_ERROR = error


def get_last_tts_error() -> str | None:
    return _LAST_TTS_ERROR


def _bounded_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _clean_tts_text(text: str) -> str:
    cleaned = str(text or "").strip()
    return cleaned[:4096]


def _openai_voice_value(voice_id: str) -> str | dict[str, str]:
    voice = str(voice_id or "").strip() or "alloy"
    if voice.startswith("voice_"):
        return {"id": voice}
    return voice


def _openai_response_format(value: Any) -> str:
    fmt = str(value or "mp3").strip().lower()
    return fmt if fmt in OPENAI_TTS_FORMATS else "mp3"


def _local_response_format(value: Any) -> str:
    fmt = str(value or "mp3").strip().lower()
    return fmt if fmt in LOCAL_HTTP_TTS_FORMATS else "mp3"


def _openai_instructions(config: dict[str, Any], style: str | None) -> str | None:
    parts: list[str] = []
    base = str(config.get("instructions") or "").strip()
    if base:
        parts.append(base)
    style_hint = OPENAI_TTS_STYLE_INSTRUCTIONS.get(str(style or "").strip().lower())
    if style_hint:
        parts.append(style_hint)
    instructions = " ".join(parts).strip()
    return instructions[:4096] if instructions else None


def _openai_tts_request(payload: dict[str, Any], api_key: str, timeout: float = 45.0) -> bytes:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        OPENAI_TTS_ENDPOINT,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def _local_base_url(config: dict[str, Any]) -> str:
    raw = str(config.get("local_base_url") or config.get("base_url") or "http://127.0.0.1:9881").strip()
    parsed = urllib.parse.urlparse(raw)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "http" or host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("local_http TTS base_url must be localhost-only")
    return raw.rstrip("/")


def _local_tts_request(payload: dict[str, Any], base_url: str, timeout: float = 45.0) -> tuple[bytes, str]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/api/tts",
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        content_type = response.headers.get("Content-Type", "")
        return response.read(), content_type


def _cancel_local_tts_request(base_url: str, request_id: str) -> None:
    request = urllib.request.Request(f"{base_url}/api/tts/{urllib.parse.quote(request_id)}", method="DELETE")
    try:
        with urllib.request.urlopen(request, timeout=3):
            pass
    except Exception:
        # The stream may already have completed and released the one local GPU job.
        pass


def stream_local_http_tts_wav(
    text: str,
    *,
    voice_id: str | None = None,
    request_id: str,
) -> Iterator[bytes]:
    """Proxy the local GPT-SoVITS PCM WAV stream without buffering it into a file."""
    cleaned = _clean_tts_text(text)
    if not cleaned:
        raise ValueError("voice text is empty")
    config = load_voice_config()
    provider = str(config.get("tts_provider", "openai_tts") or "openai_tts").strip().lower()
    if provider != "local_http":
        raise ValueError("streaming voice requires the local_http provider")
    base_url = _local_base_url(config)
    selected_voice = str(voice_id or config.get("voice_id") or "mio").strip() or "mio"
    payload = {
        "voice_id": selected_voice,
        "text": cleaned,
        "format": "wav",
        "speed": _bounded_float(config.get("rate"), 1.0, 0.6, 1.5),
        "request_id": request_id,
    }
    timeout = _bounded_float(config.get("timeout_seconds"), 45.0, 1.0, 120.0)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/api/tts-stream",
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        detail = _http_error_detail(exc)
        _set_tts_error(f"local streaming TTS HTTP {exc.code}: {detail}")
        raise RuntimeError(get_last_tts_error()) from exc
    except urllib.error.URLError as exc:
        _set_tts_error(f"local streaming TTS network error: {exc.reason}")
        raise RuntimeError(get_last_tts_error()) from exc
    except Exception as exc:
        _set_tts_error(f"local streaming TTS error: {exc}")
        raise RuntimeError(get_last_tts_error()) from exc

    content_type = str(response.headers.get("Content-Type", "")).lower()
    if "audio/wav" not in content_type:
        response.close()
        _set_tts_error(f"local streaming TTS returned unexpected content type: {content_type}")
        raise RuntimeError(get_last_tts_error())

    def chunks() -> Iterator[bytes]:
        try:
            while True:
                chunk = response.read(16 * 1024)
                if not chunk:
                    break
                yield chunk
            _set_tts_error(None)
        except Exception as exc:
            _set_tts_error(f"local streaming TTS read error: {exc}")
            raise
        finally:
            response.close()
            _cancel_local_tts_request(base_url, request_id)

    return chunks()


def _http_error_detail(error: urllib.error.HTTPError) -> str:
    try:
        raw = error.read().decode("utf-8", errors="replace")
    except Exception:
        raw = ""
    if not raw:
        return str(error)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw[:300]
    if isinstance(parsed, dict):
        detail = parsed.get("error")
        if isinstance(detail, dict):
            message = detail.get("message")
            if message:
                return str(message)[:300]
        if detail:
            return str(detail)[:300]
    return raw[:300]


def _generate_openai_tts_audio(
    text: str,
    config: dict[str, Any],
    voice_id: str | None,
    rate: float,
    style: str | None,
) -> bytes | None:
    cleaned = _clean_tts_text(text)
    if not cleaned:
        _set_tts_error("voice text is empty")
        return None

    api_key_env = str(config.get("api_key_env") or "OPENAI_API_KEY").strip() or "OPENAI_API_KEY"
    api_key = os.environ.get(api_key_env)
    if not api_key:
        _set_tts_error(f"missing API key environment variable: {api_key_env}")
        return None

    model = str(config.get("tts_model") or config.get("model") or "gpt-4o-mini-tts").strip()
    fmt = _openai_response_format(config.get("response_format"))
    selected_voice = str(voice_id or config.get("voice_id") or "alloy").strip() or "alloy"
    payload: dict[str, Any] = {
        "model": model,
        "input": cleaned,
        "voice": _openai_voice_value(selected_voice),
        "response_format": fmt,
        "speed": _bounded_float(rate if rate is not None else config.get("rate"), 1.0, 0.25, 4.0),
    }

    instructions = _openai_instructions(config, style)
    if instructions:
        payload["instructions"] = instructions

    timeout = _bounded_float(config.get("timeout_seconds"), 45.0, 1.0, 120.0)
    try:
        audio = _openai_tts_request(payload, api_key, timeout)
    except urllib.error.HTTPError as exc:
        _set_tts_error(f"OpenAI TTS HTTP {exc.code}: {_http_error_detail(exc)}")
        return None
    except urllib.error.URLError as exc:
        _set_tts_error(f"OpenAI TTS network error: {exc.reason}")
        return None
    except Exception as exc:
        _set_tts_error(f"OpenAI TTS error: {exc}")
        return None

    if not audio:
        _set_tts_error("OpenAI TTS returned empty audio")
        return None
    _set_tts_error(None)
    return audio


def _generate_local_http_tts_audio(
    text: str,
    config: dict[str, Any],
    voice_id: str | None,
    rate: float,
) -> bytes | None:
    cleaned = _clean_tts_text(text)
    if not cleaned:
        _set_tts_error("voice text is empty")
        return None

    try:
        base_url = _local_base_url(config)
    except ValueError as exc:
        _set_tts_error(str(exc))
        return None

    fmt = _local_response_format(config.get("response_format"))
    selected_voice = str(voice_id or config.get("voice_id") or "mio").strip() or "mio"
    payload: dict[str, Any] = {
        "voice_id": selected_voice,
        "text": cleaned,
        "format": fmt,
        "speed": _bounded_float(rate if rate is not None else config.get("rate"), 1.0, 0.6, 1.5),
    }
    timeout = _bounded_float(config.get("timeout_seconds"), 45.0, 1.0, 120.0)
    try:
        audio, content_type = _local_tts_request(payload, base_url, timeout)
    except urllib.error.HTTPError as exc:
        _set_tts_error(f"local TTS HTTP {exc.code}: {_http_error_detail(exc)}")
        return None
    except urllib.error.URLError as exc:
        _set_tts_error(f"local TTS network error: {exc.reason}")
        return None
    except Exception as exc:
        _set_tts_error(f"local TTS error: {exc}")
        return None

    if not audio:
        _set_tts_error("local TTS returned empty audio")
        return None
    expected = "audio/mpeg" if fmt == "mp3" else "audio/wav"
    if expected not in str(content_type).lower():
        _set_tts_error(f"local TTS returned unexpected content type: {content_type}")
        return None
    _set_tts_error(None)
    return audio


def generate_tts_audio(text: str, voice_id: str | None = None, rate: float = 1.0, pitch: float = 1.0, style: str | None = None) -> bytes | None:
    """Generate TTS audio bytes for a single utterance. Returns None on failure."""
    if not voice_enabled():
        _set_tts_error("voice is disabled")
        return None

    config = load_voice_config()
    provider = str(config.get("tts_provider", "openai_tts") or "openai_tts").strip().lower()

    if provider == "edge":
        _set_tts_error("edge TTS is disabled for LING; use the main OpenAI TTS reply voice or Video Companion realtime speech")
        return None
    if provider == "local_http":
        return _generate_local_http_tts_audio(text, config, voice_id, rate)
    if provider == "openai_tts":
        return _generate_openai_tts_audio(text, config, voice_id, rate, style)
    _set_tts_error(f"unsupported TTS provider: {provider}")
    return None


def generate_tts_reply_audio(
    reply_text: str,
    expression_labels: list[str] | None = None,
    voice_id: str | None = None,
) -> dict[str, Any]:
    """Generate TTS audio for a full reply. Returns audio bytes and metadata.

    Returns dict with:
      - success: bool
      - audio: bytes (concatenated MP3) or None
      - chunks: list of per-utterance result dicts
      - utterances: list of text strings
      - error: str or None
    """
    if not voice_enabled():
        return {"success": False, "audio": None, "chunks": [], "utterances": [], "error": "voice is disabled"}

    config = load_voice_config()
    provider = str(config.get("tts_provider", "openai_tts") or "openai_tts").strip().lower()
    response_format = _local_response_format(config.get("response_format")) if provider == "local_http" else _openai_response_format(config.get("response_format"))
    if provider == "local_http" and response_format == "mp3":
        # MP3 byte streams are not safely concatenable. The local GPT-SoVITS service
        # returns complete MP3 files, so split-and-append can introduce audible seams
        # and some browsers stop after the first embedded MP3 stream. Generate one
        # complete reply audio file for local playback instead.
        cleaned = _clean_tts_text(reply_text)
        if not cleaned:
            return {"success": False, "audio": None, "chunks": [], "utterances": [], "error": "empty reply"}
        audio = generate_tts_audio(cleaned, voice_id=voice_id)
        chunk = {
            "index": 0,
            "text": cleaned,
            "style": None,
            "audio_available": audio is not None and len(audio) > 0,
            "audio_size": len(audio) if audio else 0,
        }
        if not audio:
            chunk["error"] = get_last_tts_error() or "audio generation failed"
        return {
            "success": bool(audio),
            "audio": audio,
            "chunks": [chunk],
            "utterances": [cleaned],
            "error": None if audio else (chunk.get("error") or "audio generation failed"),
        }

    utterances = split_reply_into_utterances(reply_text)
    if not utterances:
        return {"success": False, "audio": None, "chunks": [], "utterances": [], "error": "empty reply"}

    params = build_tts_request_params(utterances, expression_labels)
    chunks: list[dict] = []
    audio_buffer = io.BytesIO()
    all_success = True

    for i, param in enumerate(params):
        audio = generate_tts_audio(
            text=param["text"],
            voice_id=voice_id or param.get("voice_id"),
            rate=float(param.get("rate", 1.0)),
            pitch=float(param.get("pitch", 1.0)),
            style=param.get("style"),
        )
        chunk_result = {
            "index": i,
            "text": param["text"],
            "style": param.get("style"),
            "audio_available": audio is not None and len(audio) > 0,
            "audio_size": len(audio) if audio else 0,
        }
        if not audio:
            chunk_result["error"] = get_last_tts_error() or "audio generation failed"
        chunks.append(chunk_result)
        if audio:
            audio_buffer.write(audio)
        else:
            all_success = False

    audio_bytes = audio_buffer.getvalue() if audio_buffer.tell() > 0 else None

    return {
        "success": all_success and audio_bytes is not None,
        "audio": audio_bytes,
        "chunks": chunks,
        "utterances": utterances,
        "error": None if (all_success and audio_bytes) else "some utterances failed to generate",
    }


def generate_tts_single_chunk(
    reply_text: str,
    chunk_index: int,
    expression_labels: list[str] | None = None,
    voice_id: str | None = None,
) -> tuple[bytes | None, dict[str, Any]]:
    """Generate TTS audio for a single utterance chunk by index.

    Returns (audio_bytes, metadata) tuple.
    """
    if not voice_enabled():
        return None, {"error": "voice is disabled"}

    utterances = split_reply_into_utterances(reply_text)
    if chunk_index < 0 or chunk_index >= len(utterances):
        return None, {"error": f"chunk_index {chunk_index} out of range (0-{len(utterances)-1})"}

    params = build_tts_request_params(utterances, expression_labels)
    param = params[chunk_index]

    audio = generate_tts_audio(
        text=param["text"],
        voice_id=voice_id or param.get("voice_id"),
        rate=float(param.get("rate", 1.0)),
        pitch=float(param.get("pitch", 1.0)),
        style=param.get("style"),
    )

    metadata = {
        "index": chunk_index,
        "text": param["text"],
        "total_chunks": len(utterances),
        "style": param.get("style"),
        "audio_available": audio is not None and len(audio) > 0,
    }
    if not audio:
        metadata["error"] = get_last_tts_error() or "audio generation failed"
    return audio, metadata


def tts_health_check() -> dict:
    """Check if TTS provider is available."""
    config = load_voice_config()
    provider = str(config.get("tts_provider", "openai_tts") or "openai_tts").strip().lower()
    result = {
        "enabled": voice_enabled(),
        "provider": provider,
        "model": config.get("tts_model") or config.get("model") or "",
        "voice_id": config.get("voice_id", "alloy"),
        "api_key_env": str(config.get("api_key_env") or "OPENAI_API_KEY"),
        "response_format": _local_response_format(config.get("response_format"))
        if provider == "local_http"
        else _openai_response_format(config.get("response_format")),
        "available": False,
        "error": None,
    }

    if not result["enabled"]:
        result["available"] = False
        result["error"] = "voice is disabled in config"
        return result

    if provider == "edge":
        result["error"] = "edge TTS is disabled for LING; use the main OpenAI TTS reply voice or Video Companion realtime speech"
    elif provider == "local_http":
        try:
            base_url = _local_base_url(config)
            timeout = _bounded_float(config.get("timeout_seconds"), 3.0, 1.0, 30.0)
            req = urllib.request.Request(f"{base_url}/api/health", method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as response:
                result["available"] = 200 <= response.status < 300
            result["base_url"] = base_url
            if not result["available"]:
                result["error"] = "local TTS health check failed"
        except Exception as exc:
            result["error"] = f"local TTS unavailable: {exc}"
    elif provider == "openai_tts":
        api_key_env = str(config.get("api_key_env") or "OPENAI_API_KEY").strip() or "OPENAI_API_KEY"
        if os.environ.get(api_key_env):
            result["available"] = True
        else:
            result["error"] = f"missing API key environment variable: {api_key_env}"
    else:
        result["error"] = f"unsupported TTS provider: {provider}"

    return result
