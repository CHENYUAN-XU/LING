from __future__ import annotations

from typing import Any


def persona_embodiment_profile(persona: dict[str, Any] | None) -> dict[str, Any]:
    item = persona or {}
    live2d_preview_url = str(item.get("live2d_preview_url") or "").strip()
    fallback_image_url = str(item.get("fallback_image_url") or "").strip()
    avatar_url = str(item.get("avatar_url") or "").strip()
    visual_url = ""
    visual_source = "none"
    for source, value in (
        ("live2d_preview_url", live2d_preview_url),
        ("fallback_image_url", fallback_image_url),
        ("avatar_url", avatar_url),
    ):
        if value:
            visual_url = value
            visual_source = source
            break

    live2d_model_id = str(item.get("live2d_model_id") or "").strip()
    voice_profile = str(item.get("voice_profile") or "").strip()
    return {
        "live2d_model_id": live2d_model_id,
        "live2d_preview_url": live2d_preview_url,
        "fallback_image_url": fallback_image_url,
        "legacy_avatar_url": avatar_url,
        "visual_url": visual_url,
        "visual_source": visual_source,
        "voice_profile": voice_profile,
        "live2d_bound": bool(live2d_model_id),
        "visual_ready": bool(visual_url),
        "voice_bound": bool(voice_profile),
    }
