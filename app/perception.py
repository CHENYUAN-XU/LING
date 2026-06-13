from __future__ import annotations

from typing import Any

from .config import load_config
from .camera_perception import (
    camera_enabled,
    detect_person_presence,
    get_camera_config,
    get_camera_status,
    _capture_frame,
)
from .world_state import (
    get_recent_world_observations,
    get_world_state_summary,
    store_world_observation,
)


def perception_enabled(user_id: int | None = None) -> bool:
    return camera_enabled(user_id)


def run_perception_cycle(user_id: int) -> dict[str, Any]:
    """Run one cycle of camera perception. Stores observations in world_state."""
    if not camera_enabled(user_id):
        return {"cycle": "disabled"}

    config = get_camera_config()
    result: dict[str, Any] = {
        "cycle": "completed",
        "observations": [],
        "presence_event": None,
    }

    if config.get("detect_presence"):
        frame_result = _capture_frame(config.get("capture_source", 0), user_id=user_id, include_frame=True)
        if frame_result and frame_result.get("has_content"):
            presence = detect_person_presence(frame_result)
            frame_result["frame"] = None
            result["presence_event"] = presence

            if presence.get("person_detected"):
                obs = store_world_observation(
                    user_id=user_id,
                    source="camera",
                    observation_type="user_presence",
                    content="User detected in camera frame",
                    confidence=float(presence.get("confidence", 0.5)),
                    metadata={"source": "camera_perception"},
                )
                result["observations"].append(obs)

    return result


def get_perception_summary(user_id: int) -> dict[str, Any]:
    return {
        "enabled": perception_enabled(user_id),
        "camera": get_camera_status(user_id),
        "world_state": get_world_state_summary(user_id),
    }
