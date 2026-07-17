from __future__ import annotations

from typing import Any


def persona_embodiment_profile(persona: dict[str, Any] | None) -> dict[str, Any]:
    item = persona or {}
    live2d_preview_url = str(item.get("live2d_preview_url") or "").strip()
    fallback_image_url = str(item.get("fallback_image_url") or "").strip()
    avatar_url = str(item.get("avatar_url") or "").strip()
    visual_url = ""
    visual_source = "none"
    visual_label = "临时形象待绑定"
    visual_tone = "missing"
    for source, value, label, tone in (
        ("live2d_preview_url", live2d_preview_url, "临时静态形象", "preview"),
        ("fallback_image_url", fallback_image_url, "Fallback image", "fallback"),
        ("avatar_url", avatar_url, "Legacy avatar fallback", "legacy"),
    ):
        if value:
            visual_url = value
            visual_source = source
            visual_label = label
            visual_tone = tone
            break

    live2d_model_id = str(item.get("live2d_model_id") or "").strip()
    voice_profile = str(item.get("voice_profile") or "").strip()
    visual_bound = bool(live2d_preview_url or fallback_image_url)
    return {
        "live2d_model_id": live2d_model_id,
        "live2d_preview_url": live2d_preview_url,
        "fallback_image_url": fallback_image_url,
        "legacy_avatar_url": avatar_url,
        "visual_url": visual_url,
        "visual_source": visual_source,
        "visual_label": visual_label,
        "visual_tone": visual_tone,
        "visual_bound": visual_bound,
        "visual_legacy_only": bool(avatar_url and not visual_bound),
        "voice_profile": voice_profile,
        "live2d_bound": bool(live2d_model_id),
        "visual_ready": visual_bound,
        "voice_bound": bool(voice_profile),
    }
