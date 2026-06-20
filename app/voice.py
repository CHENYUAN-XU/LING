from __future__ import annotations

from typing import Any

from .config import load_config


DEFAULT_VOICE_CONFIG: dict[str, Any] = {
    "enabled": False,
    "auto_play": True,
    "tts_provider": "openai_tts",
    "tts_model": "gpt-4o-mini-tts",
    "api_key_env": "OPENAI_API_KEY",
    "voice_id": "alloy",
    "response_format": "mp3",
    "instructions": "",
    "rate": 1.0,
    "pitch": 1.0,
    "split_long_replies": True,
    "max_chunk_length": 80,
    "expression_style_map": {
        "微笑": "cheerful",
        "轻笑": "cheerful",
        "担心": "concerned",
        "轻声": "gentle",
        "停顿": "default",
        "点头": "default",
    },
}


def load_voice_config() -> dict[str, Any]:
    config = load_config()
    voice = config.get("voice", {}) or {}
    if not isinstance(voice, dict):
        voice = {}
    merged = dict(DEFAULT_VOICE_CONFIG)
    for key, value in voice.items():
        if key in merged:
            merged[key] = value
    return merged


def voice_enabled() -> bool:
    return bool(load_voice_config().get("enabled", False))
