from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config.yaml"

DEFAULT_CONFIG: dict[str, Any] = {
    "active_persona": "",
    "llm": {
        "provider": "kimi",
        "model": "kimi-k2.6",
        "base_url": "https://api.moonshot.ai/v1",
        "api_key_env": "MOONSHOT_API_KEY",
        "temperature": 0.75,
    },
    "llm_routes": {},
    "memory": {
        "mode": "balanced",
        "short_term_turns": 8,
        "extract_every": 2,
        "consolidate_every": 10,
    },
    "database": {
        "journal_mode": "wal",
        "busy_timeout_ms": 5000,
    },
    "security": {
        "secure_cookies": False,
    },
    "self_use": {
        "enabled": False,
        "username": "mio_owner",
        "nickname": "",
        "require_localhost": True,
        "seed_default_persona": True,
        "default_persona_name": "澪",
        "chat_enabled": False,
    },
    "voice": {
        "enabled": False,
        "auto_play": True,
        "tts_provider": "openai_tts",
        "tts_model": "gpt-4o-mini-tts",
        "api_key_env": "OPENAI_API_KEY",
        "voice_id": "alloy",
        "response_format": "mp3",
        "local_base_url": "http://127.0.0.1:9881",
        "timeout_seconds": 45.0,
        "instructions": "",
        "rate": 1.0,
        "pitch": 1.0,
        "split_long_replies": True,
        "max_chunk_length": 80,
    },
}


def _deep_merge(defaults: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    result = dict(defaults)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        return DEFAULT_CONFIG.copy()

    with CONFIG_FILE.open("r", encoding="utf-8") as f:
        loaded = yaml.safe_load(f) or {}

    if not isinstance(loaded, dict):
        raise ValueError("config.yaml must contain a YAML object")

    return _deep_merge(DEFAULT_CONFIG, loaded)


def set_self_use_chat_enabled(enabled: bool, config_file: Path = CONFIG_FILE) -> None:
    set_config_section_bool("self_use", "chat_enabled", enabled, config_file)


def set_config_section_bool(section: str, key: str, enabled: bool, config_file: Path = CONFIG_FILE) -> None:
    set_config_section_value(section, key, bool(enabled), config_file)


def set_config_section_value(section: str, key: str, value: str | bool, config_file: Path = CONFIG_FILE) -> None:
    section = str(section or "").strip()
    key = str(key or "").strip()
    if not section or not key:
        raise ValueError("section and key are required")
    yaml_value = _yaml_scalar(value)
    if not config_file.exists():
        config = _deep_merge(DEFAULT_CONFIG, {section: {key: value}})
        config_file.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return

    lines = config_file.read_text(encoding="utf-8").splitlines(keepends=True)
    section_start = -1
    section_indent = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == f"{section}:":
            section_start = index
            section_indent = len(line) - len(line.lstrip(" "))
            break

    if section_start < 0:
        suffix = "" if not lines or lines[-1].endswith(("\n", "\r")) else "\n"
        lines.append(f"{suffix}{section}:\n  {key}: {yaml_value}\n")
        config_file.write_text("".join(lines), encoding="utf-8")
        return

    section_end = len(lines)
    child_indent = section_indent + 2
    target_index = -1
    for index in range(section_start + 1, len(lines)):
        line = lines[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent <= section_indent:
            section_end = index
            break
        child_indent = indent
        if stripped.startswith(f"{key}:"):
            target_index = index
            break

    if target_index >= 0:
        newline = "\r\n" if lines[target_index].endswith("\r\n") else "\n"
        comment = ""
        if "#" in lines[target_index]:
            comment = "  #" + lines[target_index].split("#", 1)[1].rstrip("\r\n")
        lines[target_index] = f"{' ' * child_indent}{key}: {yaml_value}{comment}{newline}"
    else:
        newline = "\r\n" if any(line.endswith("\r\n") for line in lines) else "\n"
        lines.insert(section_end, f"{' ' * child_indent}{key}: {yaml_value}{newline}")

    config_file.write_text("".join(lines), encoding="utf-8")


def _yaml_scalar(value: str | bool) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    return json.dumps(text, ensure_ascii=False)
