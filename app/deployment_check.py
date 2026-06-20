from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import BASE_DIR, load_config
from .environment_check import inspect_environment


def deployment_report(
    config: dict[str, Any] | None = None,
    *,
    production: bool = False,
    self_use: bool = False,
) -> dict[str, Any]:
    cfg = config or load_config()
    checks: list[dict[str, str]] = []
    env = inspect_environment(cfg)

    _add(
        checks,
        "api_keys",
        "pass" if not env["missing"] else ("fail" if production and not self_use else "warn"),
        "all configured API key environment variables are present"
        if not env["missing"]
        else "missing API key environment variables: " + ", ".join(env["missing"]),
    )
    _add(
        checks,
        "secrets_in_config",
        "pass" if not env["secrets_in_config"] else "fail",
        "no secret-like values found in config"
        if not env["secrets_in_config"]
        else "secret-like values found at: " + ", ".join(item["path"] for item in env["secrets_in_config"]),
    )

    rate_limit = cfg.get("rate_limit", {}) if isinstance(cfg.get("rate_limit"), dict) else {}
    _add(
        checks,
        "rate_limit",
        "pass" if rate_limit.get("enabled", False) else ("fail" if production and not self_use else "warn"),
        "rate_limit.enabled is true" if rate_limit.get("enabled", False) else "rate_limit.enabled is false",
    )

    logging_cfg = cfg.get("logging", {}) if isinstance(cfg.get("logging"), dict) else {}
    logging_enabled = bool(logging_cfg.get("enabled", False) and logging_cfg.get("request_log_enabled", False))
    _add(
        checks,
        "request_logging",
        "pass" if logging_enabled else ("fail" if production and not self_use else "warn"),
        "request logging is enabled" if logging_enabled else "request logging is disabled",
    )

    security = cfg.get("security", {}) if isinstance(cfg.get("security"), dict) else {}
    secure_cookies = bool(security.get("secure_cookies", False))
    if self_use:
        _add(
            checks,
            "secure_cookies",
            "fail" if secure_cookies else "pass",
            "secure cookies must stay disabled for the local HTTP self-use workspace"
            if secure_cookies
            else "secure cookies disabled for local HTTP self-use",
        )
    else:
        _add(
            checks,
            "secure_cookies",
            "pass" if secure_cookies or not production else "fail",
            "secure cookies enabled"
            if secure_cookies
            else "secure cookies disabled; acceptable only for local HTTP development",
        )

    self_use_cfg = cfg.get("self_use", {}) if isinstance(cfg.get("self_use"), dict) else {}
    local_self_use = bool(self_use_cfg.get("enabled", False) and self_use_cfg.get("require_localhost", True))
    _add(
        checks,
        "self_use_boundary",
        "pass" if not self_use or local_self_use else "fail",
        "LING self-use is enabled and restricted to localhost"
        if local_self_use
        else ("self_use.enabled and self_use.require_localhost must be true" if self_use else "self-use mode not requested"),
    )

    data_parent = (BASE_DIR / "data").parent
    _add(
        checks,
        "data_directory",
        "pass" if data_parent.exists() else "fail",
        f"runtime data directory parent exists: {BASE_DIR / 'data'}",
    )
    for name, path in (
        ("data_writable", BASE_DIR / "data"),
        ("uploads_writable", BASE_DIR / "data" / "uploads"),
        ("backups_writable", BASE_DIR / "data" / "backups"),
    ):
        writable, detail = _writable_directory(path)
        _add(checks, name, "pass" if writable else "fail", detail)

    video_cfg = cfg.get("video_companion", {}) if isinstance(cfg.get("video_companion"), dict) else {}
    video_enabled = bool(video_cfg.get("enabled", False))
    video_path = Path(str(video_cfg.get("project_path") or ""))
    _add(
        checks,
        "video_companion_boundary",
        "pass" if not video_enabled or video_path.exists() else "fail",
        "Video Companion disabled in main config"
        if not video_enabled
        else f"Video Companion external path {'exists' if video_path.exists() else 'is missing'}: {video_path}",
    )

    proactive = cfg.get("proactive", {}) if isinstance(cfg.get("proactive"), dict) else {}
    scheduler_enabled = bool(proactive.get("scheduler_enabled", False))
    _add(
        checks,
        "proactive_scheduler",
        "pass" if not scheduler_enabled else "warn",
        "proactive scheduler disabled by default"
        if not scheduler_enabled
        else "proactive scheduler enabled; confirm quota and quiet-hour policy before public deployment",
    )

    failed = [check for check in checks if check["status"] == "fail"]
    warnings = [check for check in checks if check["status"] == "warn"]
    return {
        "ok": not failed,
        "production": production,
        "self_use": self_use,
        "checks": checks,
        "summary": {
            "failed": len(failed),
            "warnings": len(warnings),
            "passed": len([check for check in checks if check["status"] == "pass"]),
        },
    }


def _add(checks: list[dict[str, str]], name: str, status: str, detail: str) -> None:
    checks.append({"name": name, "status": status, "detail": detail})


def _writable_directory(path: Path) -> tuple[bool, str]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".ling-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return False, f"runtime directory is not writable: {path} ({exc})"
    return True, f"runtime directory is writable: {path}"
