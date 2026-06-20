from __future__ import annotations

import threading
import time
from typing import Any

from .config import load_config


PRESENCE_STATES = ("idle", "thinking", "speaking", "quiet", "sleeping")

DEFAULT_PRESENCE_CONFIG: dict[str, Any] = {
    "enabled": False,
    "idle_timeout_seconds": 30,
    "thinking_timeout_seconds": 15,
    "idle_actions": ["idle_breath", "idle_blink", "idle_look_around"],
}


class RuntimeState:
    """Thread-safe runtime presence state manager."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state = "idle"
        self._previous_state = "idle"
        self._state_started_at = time.time()
        self._last_user_interaction = time.time()
        self._quiet_mode = False
        self._session_active = True

    @property
    def current_state(self) -> str:
        with self._lock:
            return self._state

    @property
    def previous_state(self) -> str:
        with self._lock:
            return self._previous_state

    @property
    def is_quiet(self) -> bool:
        with self._lock:
            return self._quiet_mode

    @property
    def time_since_last_interaction(self) -> float:
        with self._lock:
            return time.time() - self._last_user_interaction

    def transition_to(self, new_state: str) -> str:
        if new_state not in PRESENCE_STATES:
            return self._state

        with self._lock:
            self._previous_state = self._state
            self._state = new_state
            self._state_started_at = time.time()
            return self._state

    def touch_interaction(self) -> None:
        with self._lock:
            self._last_user_interaction = time.time()

    def set_quiet_mode(self, quiet: bool) -> None:
        with self._lock:
            self._quiet_mode = quiet
            if quiet and self._state not in ("quiet", "sleeping"):
                self._previous_state = self._state
                self._state = "quiet"
                self._state_started_at = time.time()
            elif not quiet and self._state == "quiet":
                self._previous_state = "quiet"
                self._state = "idle"
                self._state_started_at = time.time()

    def get_snapshot(self) -> dict:
        with self._lock:
            now = time.time()
            return {
                "state": self._state,
                "previous_state": self._previous_state,
                "state_duration_seconds": now - self._state_started_at,
                "seconds_since_last_interaction": now - self._last_user_interaction,
                "quiet_mode": self._quiet_mode,
                "session_active": self._session_active,
            }

    def check_idle_timeout(self) -> bool:
        config = load_config()
        presence_cfg = config.get("presence", {}) or {}
        idle_timeout = int(presence_cfg.get("idle_timeout_seconds", 30))
        with self._lock:
            if self._state == "speaking":
                return False
            elapsed = time.time() - self._last_user_interaction
            return elapsed > idle_timeout and self._state != "idle"


_runtime_state: RuntimeState | None = None
_runtime_states: dict[str, RuntimeState] = {}
_runtime_states_lock = threading.Lock()


def get_runtime_state(scope_id: int | str | None = None) -> RuntimeState:
    global _runtime_state
    if scope_id is not None:
        key = str(scope_id)
        with _runtime_states_lock:
            state = _runtime_states.get(key)
            if state is None:
                state = RuntimeState()
                _runtime_states[key] = state
            return state

    if _runtime_state is None:
        _runtime_state = RuntimeState()
    return _runtime_state


def presence_enabled() -> bool:
    config = load_config()
    presence_cfg = config.get("presence", {}) or {}
    return bool(presence_cfg.get("enabled", False))
