from __future__ import annotations

import re
from typing import Any

from .voice import load_voice_config


def split_reply_into_utterances(reply: str) -> list[str]:
    """Split a reply into speakable short sentences for TTS."""
    config = load_voice_config()
    if not config.get("split_long_replies", True):
        return [reply.strip()]

    max_chunk = int(config.get("max_chunk_length", 80))

    segments = _split_by_sentence_boundary(reply.strip())

    utterances: list[str] = []
    for segment in segments:
        if len(segment) <= max_chunk:
            utterances.append(segment)
            continue
        sub_parts = _split_long_segment(segment, max_chunk)
        utterances.extend(sub_parts)

    return [u for u in utterances if u.strip()]


def _split_by_sentence_boundary(text: str) -> list[str]:
    boundaries = re.split(r"([。！？!?\n])", text)
    segments: list[str] = []
    buffer = ""
    for part in boundaries:
        if part in {"。", "！", "？", "!", "?", "\n"}:
            buffer += part
            if buffer.strip():
                segments.append(buffer.strip())
            buffer = ""
        else:
            buffer += part
    if buffer.strip():
        segments.append(buffer.strip())
    return segments


def _split_long_segment(segment: str, max_chunk: int) -> list[str]:
    parts: list[str] = []
    current = ""
    for char in segment:
        current += char
        if len(current) >= max_chunk and char in "，,、":
            parts.append(current.strip())
            current = ""
    if current.strip():
        parts.append(current.strip())
    if not parts:
        return [segment]
    return parts


def expression_label_to_voice_style(label: str) -> str | None:
    """Map expression label to TTS voice style name."""
    config = load_voice_config()
    style_map = config.get("expression_style_map", {}) or {}
    if not isinstance(style_map, dict):
        return None
    return style_map.get(str(label), None)


def build_tts_request_params(utterances: list[str], expression_labels: list[str] | None = None) -> list[dict[str, Any]]:
    """Build TTS request parameters for a list of utterances."""
    config = load_voice_config()
    params_list: list[dict[str, Any]] = []
    labels = expression_labels or []

    for i, utterance in enumerate(utterances):
        param: dict[str, Any] = {
            "text": utterance,
            "voice_id": config.get("voice_id", "alloy"),
            "rate": float(config.get("rate", 1.0)),
            "pitch": float(config.get("pitch", 1.0)),
        }
        if labels:
            style = expression_label_to_voice_style(labels[0])
            if style and style != "default":
                param["style"] = style
        params_list.append(param)

    return params_list
