from __future__ import annotations

from typing import Any

from .expression_assets import expression_asset
from .live2d import load_live2d_config, live2d_enabled


def map_expression_to_body(expression_label: str, expression_type: str = "mood") -> dict[str, Any] | None:
    """Map a light expression label to a full body expression descriptor.

    Returns a descriptor dict or None if no mapping exists.
    """
    if not live2d_enabled():
        return None

    config = load_live2d_config()
    expression_map = config.get("expression_map", {}) or {}
    if not isinstance(expression_map, dict):
        return None

    live2d_target = expression_map.get(str(expression_label))
    if not live2d_target:
        return None

    asset = expression_asset(expression_type, expression_label)
    intensity = 1
    group = "general"
    if asset:
        intensity = int(asset.get("intensity", 1))
        group = str(asset.get("group", "general"))

    return {
        "label": expression_label,
        "expression_type": expression_type,
        "live2d_expression": live2d_target,
        "intensity": intensity,
        "group": group,
        "source": "expression_label",
    }


def get_expression_categories() -> dict[str, list[str]]:
    """Get all known expression categories with their Live2D mappings."""
    if not live2d_enabled():
        return {}

    config = load_live2d_config()
    expression_map = config.get("expression_map", {}) or {}
    if not isinstance(expression_map, dict):
        return {}

    categories: dict[str, list[str]] = {"mapped": [], "unmapped": []}
    for label, target in expression_map.items():
        if target and target != "Default":
            categories["mapped"].append(f"{label} -> {target}")
        else:
            categories["unmapped"].append(label)

    return categories


def get_default_idle_action() -> str:
    config = load_live2d_config()
    idle_actions = config.get("idle_expressions", ["Default"])
    if isinstance(idle_actions, list) and idle_actions:
        return str(idle_actions[0])
    return "Default"
