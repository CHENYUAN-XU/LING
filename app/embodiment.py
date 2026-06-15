from __future__ import annotations

from typing import Any

from .expression_assets import expression_asset
from .live2d import Live2DConnection, load_live2d_config, live2d_enabled


_live2d_connection: Live2DConnection | None = None


def get_live2d_connection() -> Live2DConnection:
    global _live2d_connection
    if _live2d_connection is None:
        _live2d_connection = Live2DConnection()
    return _live2d_connection


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
        return {"applied": False, "reason": "not_connected", "expression": live2d_expr}

    applied = conn.set_expression(live2d_expr)
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
        return {"applied": False, "reason": "not_connected", "state": normalized, "expression": expression}

    applied = conn.set_expression(expression)
    return {
        "applied": applied,
        "state": normalized,
        "expression": expression,
    }


def live2d_connection_status() -> dict:
    conn = get_live2d_connection()
    status = conn.get_connection_status()
    status["config_expression_map"] = load_live2d_config().get("expression_map", {})
    return status
