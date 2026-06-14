from __future__ import annotations

import asyncio
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .voice import load_voice_config, voice_enabled
from .speech_planner import build_tts_request_params, split_reply_into_utterances


_LAST_TTS_ERROR: str | None = None


def _set_tts_error(error: str | None) -> None:
    global _LAST_TTS_ERROR
    _LAST_TTS_ERROR = error


def get_last_tts_error() -> str | None:
    return _LAST_TTS_ERROR


def generate_tts_audio(text: str, voice_id: str | None = None, rate: float = 1.0, pitch: float = 1.0, style: str | None = None) -> bytes | None:
    """Generate TTS audio bytes for a single utterance. Returns None on failure."""
    if not voice_enabled():
        _set_tts_error("voice is disabled")
        return None

    config = load_voice_config()
    provider = str(config.get("tts_provider", "openai_tts") or "openai_tts").strip().lower()

    if provider == "edge":
        return _edge_tts_text(text, voice_id, rate, pitch, style)
    if provider in {"openai_tts", "elevenlabs"}:
        _set_tts_error(
            f"{provider} is configured, but realtime speech is owned by Video Companion or a dedicated provider adapter"
        )
        return None
    _set_tts_error(f"unsupported TTS provider: {provider}")
    return None


def generate_tts_reply_audio(
    reply_text: str,
    expression_labels: list[str] | None = None,
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
            voice_id=param.get("voice_id"),
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
        voice_id=param.get("voice_id"),
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


def _edge_tts_text(text: str, voice_id: str | None = None, rate: float = 1.0, pitch: float = 1.0, style: str | None = None) -> bytes | None:
    config = load_voice_config()
    vid = voice_id or config.get("voice_id", "zh-CN-XiaoxiaoNeural")

    rate_str = f"{int((rate - 1.0) * 100):+d}%"
    pitch_str = f"{int((pitch - 1.0) * 100):+d}Hz"

    text_escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    ssml = (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis"'
        ' xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="zh-CN">'
        f'<voice name="{vid}">'
        f'<prosody rate="{rate_str}" pitch="{pitch_str}">'
        f"{text_escaped}"
        f"</prosody>"
        f"</voice>"
        f"</speak>"
    )

    try:
        import edge_tts

        communicate = edge_tts.Communicate(ssml, vid)
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_collect_audio(communicate))
        finally:
            loop.close()
        if result:
            _set_tts_error(None)
            return result
    except ImportError:
        _set_tts_error("edge-tts library is not importable; trying subprocess fallback")
    except Exception as exc:
        error = f"edge-tts library failed: {exc}"
        _set_tts_error(error)
        print(f"[TTS] {error}")

    return _edge_tts_subprocess(text, vid)


def _edge_tts_subprocess(text: str, voice_id: str) -> bytes | None:
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
            tmp_path = tmp_file.name

        cmd = [
            sys.executable, "-m", "edge_tts",
            "--voice", voice_id,
            "--text", text,
            "--write-media", tmp_path,
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )

        if result.returncode != 0:
            stderr = (result.stderr or "")[:300]
            error = f"edge-tts failed: {stderr}" if stderr else "edge-tts failed"
            _set_tts_error(error)
            print(f"[TTS] {error}")
            return None

        if tmp_path and Path(tmp_path).exists():
            audio_data = Path(tmp_path).read_bytes()
            if audio_data:
                _set_tts_error(None)
                return audio_data
            _set_tts_error("edge-tts wrote an empty audio file")
            return None
        _set_tts_error("edge-tts did not write an audio file")
        return None
    except FileNotFoundError:
        _set_tts_error("edge-tts not installed. Run: pip install edge-tts")
        print("[TTS] edge-tts not installed. Run: pip install edge-tts")
        return None
    except Exception as exc:
        error = f"edge-tts subprocess failed: {exc}"
        _set_tts_error(error)
        print(f"[TTS] {error}")
        return None
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass


async def _collect_audio(communicate) -> bytes:
    buffer = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buffer.write(chunk["data"])
    return buffer.getvalue()


def tts_health_check() -> dict:
    """Check if TTS provider is available."""
    config = load_voice_config()
    result = {
        "enabled": voice_enabled(),
        "provider": config.get("tts_provider", "openai_tts"),
        "voice_id": config.get("voice_id", "alloy"),
        "available": False,
        "error": None,
    }

    if not result["enabled"]:
        result["available"] = False
        result["error"] = "voice is disabled in config"
        return result

    provider = str(config.get("tts_provider", "openai_tts") or "openai_tts").strip().lower()
    if provider == "edge":
        try:
            import edge_tts
            result["available"] = True
        except ImportError:
            try:
                check = subprocess.run(
                    [sys.executable, "-m", "edge_tts", "--help"],
                    capture_output=True, timeout=15,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                result["available"] = check.returncode == 0
                if not result["available"]:
                    result["error"] = "edge-tts not installed. Run: pip install edge-tts"
            except Exception as exc:
                result["error"] = str(exc)
    elif provider in {"openai_tts", "elevenlabs"}:
        result["error"] = (
            f"{provider} is not implemented in the main project; use Video Companion speech configuration"
        )
    else:
        result["error"] = f"unsupported TTS provider: {provider}"

    return result
