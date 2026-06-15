from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .config import load_config


DEFAULT_VIDEO_COMPANION_CONFIG: dict[str, Any] = {
    "enabled": False,
    "base_url": "http://127.0.0.1:8782",
    "ws_url": "ws://127.0.0.1:8782/ws",
    "project_path": r"E:\视觉\video-companion",
    "timeout_seconds": 3,
}


def load_video_companion_config() -> dict[str, Any]:
    raw = load_config().get("video_companion", {})
    if not isinstance(raw, dict):
        raw = {}
    config = dict(DEFAULT_VIDEO_COMPANION_CONFIG)
    config.update(raw)
    config = _apply_env_overrides(config)
    config["enabled"] = bool(config.get("enabled", False))
    config["base_url"] = str(config.get("base_url") or DEFAULT_VIDEO_COMPANION_CONFIG["base_url"]).rstrip("/")
    config["ws_url"] = str(config.get("ws_url") or DEFAULT_VIDEO_COMPANION_CONFIG["ws_url"])
    config["project_path"] = str(config.get("project_path") or DEFAULT_VIDEO_COMPANION_CONFIG["project_path"])
    try:
        config["timeout_seconds"] = max(1.0, float(config.get("timeout_seconds", 3)))
    except (TypeError, ValueError):
        config["timeout_seconds"] = 3.0
    return config


def _apply_env_overrides(config: dict[str, Any]) -> dict[str, Any]:
    result = dict(config)
    enabled = os.environ.get("MNEMOSYNE_VIDEO_COMPANION_ENABLED")
    if enabled is not None:
        result["enabled"] = enabled.strip().lower() in {"1", "true", "yes", "on"}
    for env_name, key in (
        ("MNEMOSYNE_VIDEO_COMPANION_BASE_URL", "base_url"),
        ("MNEMOSYNE_VIDEO_COMPANION_WS_URL", "ws_url"),
        ("MNEMOSYNE_VIDEO_COMPANION_PROJECT_PATH", "project_path"),
        ("MNEMOSYNE_VIDEO_COMPANION_TIMEOUT_SECONDS", "timeout_seconds"),
    ):
        value = os.environ.get(env_name)
        if value is not None and value.strip():
            result[key] = value.strip()
    return result


def video_companion_enabled() -> bool:
    return bool(load_video_companion_config().get("enabled"))


def public_video_companion_config() -> dict[str, Any]:
    config = load_video_companion_config()
    project_path = str(config["project_path"])
    return {
        "enabled": config["enabled"],
        "base_url": config["base_url"],
        "ws_url": config["ws_url"],
        "project_path": project_path,
        "project_path_exists": Path(project_path).exists(),
    }


def get_video_companion_status() -> dict[str, Any]:
    config = load_video_companion_config()
    if not config["enabled"]:
        return {
            "enabled": False,
            "connected": False,
            "reason": "video_companion_disabled",
            "config": public_video_companion_config(),
        }

    try:
        health = _request_json("GET", "/api/health", config=config)
        status = _request_json("GET", "/api/status", config=config)
    except VideoCompanionError as exc:
        return {
            "enabled": True,
            "connected": False,
            "reason": "video_companion_unreachable",
            "error": str(exc),
            "config": public_video_companion_config(),
        }

    return {
        "enabled": True,
        "connected": True,
        "health": health,
        "status": status,
        "config": public_video_companion_config(),
    }


def start_video_companion_session(persona_id: int | str | None = None) -> dict[str, Any]:
    config = load_video_companion_config()
    if not config["enabled"]:
        return {"enabled": False, "started": False, "reason": "video_companion_disabled"}
    path = "/api/session/start"
    if persona_id is not None:
        path += "?persona_id=" + urllib.parse.quote(str(persona_id))
    result = _request_json("POST", path, config=config)
    return {"enabled": True, "started": True, "result": result}


def stop_video_companion_session() -> dict[str, Any]:
    config = load_video_companion_config()
    if not config["enabled"]:
        return {"enabled": False, "stopped": False, "reason": "video_companion_disabled"}
    result = _request_json("POST", "/api/session/stop", config=config)
    return {"enabled": True, "stopped": True, "result": result}


class VideoCompanionError(RuntimeError):
    pass


def _request_json(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = config or load_video_companion_config()
    url = f"{cfg['base_url']}{path}"
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(request, timeout=float(cfg["timeout_seconds"])) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise VideoCompanionError(f"{method} {path} failed with HTTP {exc.code}: {detail}") from exc
    except OSError as exc:
        raise VideoCompanionError(f"{method} {path} failed: {exc}") from exc

    if not raw:
        return {}
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise VideoCompanionError(f"{method} {path} returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise VideoCompanionError(f"{method} {path} returned non-object JSON")
    return decoded
