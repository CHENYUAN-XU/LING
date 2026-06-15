from __future__ import annotations

import io
import json
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
        _set_tts_error("edge TTS is disabled for LING; use Video Companion speech or a dedicated high-quality provider")
        return None
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
        result["error"] = "edge TTS is disabled for LING; use Video Companion speech or a dedicated high-quality provider"
    elif provider in {"openai_tts", "elevenlabs"}:
        result["error"] = (
            f"{provider} is not implemented in the main project; use Video Companion speech configuration"
        )
    else:
        result["error"] = f"unsupported TTS provider: {provider}"

    return result
