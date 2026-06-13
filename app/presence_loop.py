from __future__ import annotations

import time
from typing import Any

from .config import load_config
from .runtime_state import (
    PRESENCE_STATES,
    RuntimeState,
    get_runtime_state,
    presence_enabled,
)
from .live2d import live2d_enabled
from .voice import voice_enabled


def get_presence_config() -> dict:
    config = load_config()
    presence_cfg = config.get("presence", {}) or {}
    if not isinstance(presence_cfg, dict):
        presence_cfg = {}
    return {
        "enabled": bool(presence_cfg.get("enabled", False)),
        "idle_timeout_seconds": int(presence_cfg.get("idle_timeout_seconds", 30)),
        "thinking_timeout_seconds": int(presence_cfg.get("thinking_timeout_seconds", 15)),
        "idle_actions": list(presence_cfg.get("idle_actions", ["idle_breath", "idle_blink"]) or []),
    }


def on_user_message(user_id: int | None = None) -> dict[str, Any]:
    """Called when user sends a message. Triggers presence state transition."""
    if not presence_enabled():
        return {"transition": "disabled"}

    state = get_runtime_state(user_id)
    state.touch_interaction()

    previous = state.current_state
    new_state = state.transition_to("thinking")
    return {
        "transition": f"{previous} -> {new_state}",
        "previous": previous,
        "current": new_state,
    }


def on_reply_start(user_id: int | None = None) -> dict[str, Any]:
    """Called when the AI starts replying."""
    if not presence_enabled():
        return {"transition": "disabled"}

    state = get_runtime_state(user_id)
    previous = state.current_state
    if state.is_quiet:
        return {
            "transition": f"{previous} -> quiet",
            "previous": previous,
            "current": "quiet",
        }
    new_state = state.transition_to("speaking")
    return {
        "transition": f"{previous} -> {new_state}",
        "previous": previous,
        "current": new_state,
    }


def on_reply_end(user_id: int | None = None) -> dict[str, Any]:
    """Called after the AI finishes replying."""
    if not presence_enabled():
        return {"transition": "disabled"}

    state = get_runtime_state(user_id)
    previous = state.current_state
    if state.is_quiet:
        state.set_quiet_mode(True)
        return {
            "transition": f"{previous} -> quiet",
            "previous": previous,
            "current": "quiet",
        }
    new_state = state.transition_to("idle")
    return {
        "transition": f"{previous} -> {new_state}",
        "previous": previous,
        "current": new_state,
    }


def on_idle(user_id: int | None = None) -> dict[str, Any]:
    """Called when the system detects idle state. Triggers low-cost idle actions."""
    if not presence_enabled():
        return {"transition": "disabled"}

    state = get_runtime_state(user_id)
    if state.current_state != "idle":
        state.transition_to("idle")

    config = get_presence_config()
    actions = list(config.get("idle_actions", []) or [])
    return {
        "state": "idle",
        "actions": actions,
        "seconds_since_last_interaction": state.time_since_last_interaction,
    }


def on_quiet_mode_enter(user_id: int | None = None) -> dict[str, Any]:
    """Enter quiet mode."""
    if not presence_enabled():
        return {"transition": "disabled"}

    state = get_runtime_state(user_id)
    state.set_quiet_mode(True)
    return state.get_snapshot()


def on_quiet_mode_exit(user_id: int | None = None) -> dict[str, Any]:
    """Exit quiet mode."""
    if not presence_enabled():
        return {"transition": "disabled"}

    state = get_runtime_state(user_id)
    state.set_quiet_mode(False)
    return state.get_snapshot()


def detect_quiet_mode_request(user_text: str) -> bool:
    """Check if user's message requests quiet mode."""
    text = str(user_text or "").lower().replace(" ", "")
    quiet_keywords = (
        "别打扰我", "安静一点", "先别说话", "静一静",
        "别说话", "安静", "不要吵", "别吵", "别打扰",
        "让我安静", "不要打扰我", "先不要说话",
        "quietmode", "silentmode",
    )
    return any(kw in text for kw in quiet_keywords)


def get_presence_summary(user_id: int | None = None) -> dict[str, Any]:
    """Get full presence system summary."""
    if not presence_enabled():
        return {"enabled": False}

    state = get_runtime_state(user_id)
    return {
        "enabled": True,
        "runtime": state.get_snapshot(),
        "config": get_presence_config(),
        "live2d_enabled": live2d_enabled(),
        "voice_enabled": voice_enabled(),
    }


def should_show_presence_notice(user_id: int | None = None) -> bool:
    """Determine if a presence notice should be shown to the user."""
    if not presence_enabled():
        return False
    state = get_runtime_state(user_id)
    return state.is_quiet
