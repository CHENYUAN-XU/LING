from __future__ import annotations

import logging
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.request_logging import configure_request_logging, log_request


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = {
            "enabled": True,
            "request_log_enabled": True,
            "log_dir": tmp,
            "filename": "test.log",
            "max_bytes": 100_000,
            "backup_count": 1,
        }
        logger = configure_request_logging(cfg)
        log_request(
            logger,
            request_id="req-1",
            method="GET",
            path="/api/health",
            status_code=200,
            duration_ms=12,
            client_id="127.0.0.1",
        )
        log_request(
            logger,
            request_id="req-2",
            method="POST",
            path="/api/chat",
            status_code=500,
            duration_ms=34,
            client_id="127.0.0.1",
            error="RuntimeError",
        )
        request_logger = logging.getLogger("mnemosyne.request")
        for handler in request_logger.handlers:
            handler.flush()
        text = (Path(tmp) / "test.log").read_text(encoding="utf-8")
        assert "request_id=req-1" in text
        assert "status=200" in text
        assert "request_id=req-2" in text
        assert "status=500" in text
        assert "error=RuntimeError" in text
        assert "password" not in text.lower()
        for handler in list(request_logger.handlers):
            handler.flush()
            handler.close()
            request_logger.removeHandler(handler)

    print("Request logging verification passed")


if __name__ == "__main__":
    main()
