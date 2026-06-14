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
        database.DB_PATH = Path(tmp) / "admin_errors.db"
        database.init_db()

        from app.error_monitor import record_error_event
        import app.server as server

        record_error_event(
            request_id="admin-ui-error",
            method="GET",
            path="/api/broken",
            status_code=500,
            error_type="RuntimeError",
            error_text="broken for admin ui",
            client_id="127.0.0.1",
        )
        result = server.admin_error_events({"id": 1, "role": "admin"}, limit=5)
        assert result["events"][0]["request_id"] == "admin-ui-error"

    admin_js = (PROJECT_ROOT / "admin_web" / "admin.js").read_text(encoding="utf-8")
    admin_css = (PROJECT_ROOT / "admin_web" / "admin.css").read_text(encoding="utf-8")
    assert "/api/admin/error-events?limit=20" in admin_js
    assert "function renderErrorEvents()" in admin_js
    assert "服务错误" in admin_js
    assert ".error-event-list" in admin_css
    assert ".error-event" in admin_css

    print("Admin error events UI verification passed")


if __name__ == "__main__":
    main()
