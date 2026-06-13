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
        database.DB_PATH = root / "guests.db"
        database.init_db()

        import app.auth as auth
        import app.server as server

        uploads = root / "uploads"
        auth.UPLOAD_ROOT = uploads
        server.UPLOAD_DIR = uploads

        ts = database.now_ts()
        expired = auth.create_guest_user()
        active = auth.create_guest_user()
        expired_id = int(expired["id"])
        active_id = int(active["id"])
        (uploads / str(expired_id)).mkdir(parents=True)
        (uploads / str(expired_id) / "avatar.txt").write_text("guest", encoding="utf-8")

        with database.get_db() as db:
            db.execute("UPDATE users SET guest_expires_at = ? WHERE id = ?", (ts - 10, expired_id))
            db.execute("UPDATE users SET guest_expires_at = ? WHERE id = ?", (ts + 3600, active_id))

        deleted = auth.cleanup_expired_guest_users(ts)
        assert deleted == 1
        assert not (uploads / str(expired_id)).exists()

        with database.get_db() as db:
            assert db.execute("SELECT COUNT(*) AS c FROM users WHERE id = ?", (expired_id,)).fetchone()["c"] == 0
            log = db.execute("SELECT * FROM guest_cleanup_logs WHERE user_id = ?", (expired_id,)).fetchone()
            assert log is not None
            assert log["username"] == expired["username"]
            assert log["reason"] == "expired"

        guests = server.admin_guests({"id": 1, "role": "admin"}, limit=5)
        assert guests["active_guest_count"] == 1
        assert guests["expiring_24h_count"] == 1
        assert guests["cleanup_logs"][0]["user_id"] == expired_id

    print("Guest admin verification passed")


if __name__ == "__main__":
    main()
