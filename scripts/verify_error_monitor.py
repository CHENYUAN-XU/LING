from __future__ import annotations

import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app.database as database


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        database.DB_PATH = root / "errors.db"
        database.init_db()

        from app.error_monitor import list_error_events, record_error_event

        first = record_error_event(
            request_id="req-error",
            method="post",
            path="/api/chat",
            status_code=500,
            error_type="RuntimeError",
            error_text="x" * 1500,
            client_id="127.0.0.1",
        )
        second = record_error_event(
            request_id="req-gateway",
            method="GET",
            path="/api/video-companion/status",
            status_code=502,
            error_type="HTTPResponse",
            error_text="",
            client_id="127.0.0.2",
        )

        assert first is not None
        assert first["method"] == "POST"
        assert first["status_code"] == 500
        assert first["error_type"] == "RuntimeError"
        assert len(first["error_text"]) <= 1000
        assert str(first["error_text"]).endswith("...")
        assert second is not None

        all_events = list_error_events(limit=10)
        assert [event["request_id"] for event in all_events[:2]] == ["req-gateway", "req-error"]

        gateway_events = list_error_events(limit=10, status_code=502)
        assert len(gateway_events) == 1
        assert gateway_events[0]["request_id"] == "req-gateway"

        import app.server as server

        api_result = server.admin_error_events({"id": 1, "role": "admin"}, limit=10, status_code=500)
        assert len(api_result["events"]) == 1
        assert api_result["events"][0]["request_id"] == "req-error"

    print("Error monitor verification passed")


if __name__ == "__main__":
    main()
