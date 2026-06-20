from __future__ import annotations

import threading
from typing import Any

from .expression_assets import expression_asset
from .live2d import Live2DConnection, load_live2d_config, live2d_enabled


_live2d_connection: Live2DConnection | None = None
_live2d_autoconnect_thread: threading.Thread | None = None
_live2d_autoconnect_lock = threading.Lock()
_live2d_autoconnect_stop = threading.Event()
_live2d_autoconnect_paused = False
LIVE2D_RECONNECT_DELAYS = (0.0, 2.0, 5.0, 10.0, 20.0)


def get_live2d_connection() -> Live2DConnection:
    global _live2d_connection
    if _live2d_connection is None:
        _live2d_connection = Live2DConnection()
    return _live2d_connection


def start_live2d_autoconnect(*, force: bool = False) -> dict[str, Any]:
    global _live2d_autoconnect_paused, _live2d_autoconnect_thread
    if not live2d_enabled():
        return {"started": False, "reason": "live2d_disabled"}

    connection = get_live2d_connection()
    if connection.is_connected:
        return {"started": False, "reason": "already_connected"}
    with _live2d_autoconnect_lock:
        if force:
            _live2d_autoconnect_paused = False
        if _live2d_autoconnect_paused:
            return {"started": False, "reason": "manually_paused"}
        thread = _live2d_autoconnect_thread
        if connection.is_connecting or (thread and thread.is_alive()):
            return {"started": False, "reason": "already_connecting"}
        _live2d_autoconnect_stop.clear()

        def connect_in_background() -> None:
            for delay in LIVE2D_RECONNECT_DELAYS:
                if delay and _live2d_autoconnect_stop.wait(delay):
                    return
                if _live2d_autoconnect_stop.is_set() or _live2d_autoconnect_paused or not live2d_enabled():
                    return
                if connection.is_connected or connection.connect():
                    return

        thread = threading.Thread(
            target=connect_in_background,
            name="ling-live2d-autoconnect",
            daemon=True,
        )
        _live2d_autoconnect_thread = thread
        thread.start()
    return {"started": True, "reason": "startup_autoconnect"}


def stop_live2d_connection(*, pause_autoconnect: bool = True) -> dict[str, Any]:
    global _live2d_autoconnect_paused
    with _live2d_autoconnect_lock:
        _live2d_autoconnect_paused = bool(pause_autoconnect)
        _live2d_autoconnect_stop.set()
    connection = get_live2d_connection()
    connection.disconnect()
    return connection.get_connection_status()


def expression_to_live2d(expression_label: str, expression_type: str = "") -> str | None:
    """Map an expression label to a Live2D expression name."""
    if not live2d_enabled():
        return None

    config = load_live2d_config()
    expression_map = config.get("expression_map", {}) or {}
    if not isinstance(expression_map, dict):
        return None

    mapped = expression_map.get(str(expression_label))
    if mapped:
        return str(mapped)

    return None


def get_expression_priority(expression_label: str) -> int:
    """Get priority for an expression. Higher = more important."""
    asset = expression_asset("mood", expression_label) or expression_asset("tone", expression_label) or expression_asset("gesture", expression_label)
    if asset:
        return int(asset.get("intensity", 1))
    return 1


def get_idle_expression() -> str:
    """Get the default idle expression."""
    config = load_live2d_config()
    idle_list = config.get("idle_expressions", ["Default"])
    if isinstance(idle_list, list) and idle_list:
        return str(idle_list[0])
    return "Default"


def get_speaking_expression() -> str:
    config = load_live2d_config()
    return str(config.get("speaking_expression", "Talking"))


def get_thinking_expression() -> str:
    config = load_live2d_config()
    return str(config.get("thinking_expression", "Thinking"))


def get_listening_expression() -> str:
    config = load_live2d_config()
    return str(config.get("listening_expression", "Listening"))


def apply_expression_to_live2d(expression_label: str, expression_type: str = "") -> dict[str, Any]:
    """Apply an expression to Live2D and return result."""
    if not live2d_enabled():
        return {"applied": False, "reason": "live2d_disabled"}

    live2d_expr = expression_to_live2d(expression_label, expression_type)
    if not live2d_expr:
        return {"applied": False, "reason": "no_mapping", "label": expression_label}

    conn = get_live2d_connection()
    if not conn.is_connected:
        start_live2d_autoconnect()
        return {"applied": False, "reason": "not_connected", "expression": live2d_expr}

    applied = conn.set_expression(live2d_expr)
    if not applied and not conn.is_connected:
        start_live2d_autoconnect()
    return {
        "applied": applied,
        "expression": live2d_expr,
        "label": expression_label,
        "expression_type": expression_type,
    }


def apply_runtime_state_to_live2d(state: str) -> dict[str, Any]:
    if not live2d_enabled():
        return {"applied": False, "reason": "live2d_disabled", "state": state}

    normalized = str(state or "").strip().lower()
    if normalized == "speaking":
        expression = get_speaking_expression()
    elif normalized == "thinking":
        expression = get_thinking_expression()
    elif normalized == "listening":
        expression = get_listening_expression()
    elif normalized in {"idle", "present"}:
        expression = get_idle_expression()
    else:
        return {"applied": False, "reason": "unsupported_state", "state": state}

    conn = get_live2d_connection()
    if not conn.is_connected:
        start_live2d_autoconnect()
        return {"applied": False, "reason": "not_connected", "state": normalized, "expression": expression}

    applied = conn.set_expression(expression)
    if not applied and not conn.is_connected:
        start_live2d_autoconnect()
    return {
        "applied": applied,
        "state": normalized,
        "expression": expression,
    }


def live2d_connection_status() -> dict:
    conn = get_live2d_connection()
    if live2d_enabled() and not conn.is_connected and not conn.is_connecting:
        start_live2d_autoconnect()
    status = conn.get_connection_status()
    status["config_expression_map"] = load_live2d_config().get("expression_map", {})
    return status
