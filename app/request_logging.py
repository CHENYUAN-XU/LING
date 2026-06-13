from __future__ import annotations

import logging
import logging.handlers
import time
from pathlib import Path
from typing import Any

from fastapi import Request

from .config import BASE_DIR, load_config


LOGGER_NAME = "mnemosyne.request"
DEFAULT_LOG_DIR = BASE_DIR / "logs"


def load_logging_config() -> dict[str, Any]:
    raw = load_config().get("logging", {})
    if not isinstance(raw, dict):
        raw = {}
    return {
        "enabled": bool(raw.get("enabled", True)),
        "request_log_enabled": bool(raw.get("request_log_enabled", True)),
        "log_dir": str(raw.get("log_dir") or DEFAULT_LOG_DIR),
        "filename": str(raw.get("filename") or "app.log"),
        "max_bytes": int(raw.get("max_bytes") or 2_000_000),
        "backup_count": int(raw.get("backup_count") or 5),
    }


def configure_request_logging(config: dict[str, Any] | None = None) -> logging.Logger:
    cfg = config or load_logging_config()
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not cfg.get("enabled", True):
        logger.disabled = True
        return logger

    logger.disabled = False
    log_dir = Path(str(cfg.get("log_dir") or DEFAULT_LOG_DIR))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / str(cfg.get("filename") or "app.log")
    marker = str(log_path.resolve())
    for handler in logger.handlers:
        if getattr(handler, "_mnemosyne_log_path", None) == marker:
            return logger

    handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=int(cfg.get("max_bytes") or 2_000_000),
        backupCount=int(cfg.get("backup_count") or 5),
        encoding="utf-8",
    )
    handler._mnemosyne_log_path = marker  # type: ignore[attr-defined]
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


def request_client_id(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    if forwarded:
        return forwarded
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def request_log_enabled(config: dict[str, Any] | None = None) -> bool:
    cfg = config or load_logging_config()
    return bool(cfg.get("enabled", True) and cfg.get("request_log_enabled", True))


def log_request(
    logger: logging.Logger,
    *,
    request_id: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: int,
    client_id: str,
    error: str = "",
) -> None:
    message = (
        f"request_id={request_id} method={method} path={path} "
        f"status={status_code} duration_ms={duration_ms} client={client_id}"
    )
    if error:
        message += f" error={error}"
    if status_code >= 500:
        logger.error(message)
    else:
        logger.info(message)


def elapsed_ms(start: float) -> int:
    return max(0, int((time.perf_counter() - start) * 1000))
