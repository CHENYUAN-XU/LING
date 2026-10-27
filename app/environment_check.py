from __future__ import annotations

import os
import re
from typing import Any

from .config import load_config


SECRET_VALUE_RE = re.compile(r"(sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._-]{12,}|api[_-]?key\s*[:=])", re.IGNORECASE)


def inspect_environment(config: dict[str, Any] | None = None, *, include_values: bool = False) -> dict[str, Any]:
    cfg = config or load_config()
    env_names = sorted(_api_key_env_names(cfg))
    missing = [name for name in env_names if not os.environ.get(name)]
    present = [name for name in env_names if os.environ.get(name)]
    return {
        "required_env": env_names,
        "present": present,
        "missing": missing,
        "secrets_in_config": find_secret_like_config_values(cfg, include_values=include_values),
    }


def find_secret_like_config_values(config: dict[str, Any], *, include_values: bool = False) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, f"{path}.{key}" if path else str(key))
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                visit(child, f"{path}[{idx}]")
        elif isinstance(value, str):
            if SECRET_VALUE_RE.search(value) and not path.endswith("api_key_env"):
                item = {"path": path}
                if include_values:
                    item["value"] = value
                findings.append(item)

    visit(config, "")
    return findings


def _api_key_env_names(config: dict[str, Any]) -> set[str]:
    names: set[str] = set()

    def visit(value: Any, path: tuple[str, ...] = ()) -> None:
        if isinstance(value, dict):
            env_name = value.get("api_key_env")
            section = path[-1] if path else ""
            section_enabled = bool(value.get("enabled", False)) if "enabled" in value else True
            if section == "voice" and (not section_enabled or value.get("tts_provider") == "local_http"):
                env_name = ""
            if isinstance(env_name, str) and env_name.strip():
                names.add(env_name.strip())
            for key, child in value.items():
                visit(child, (*path, str(key)))
        elif isinstance(value, list):
            for child in value:
                visit(child, path)

    visit(config)
    return names
