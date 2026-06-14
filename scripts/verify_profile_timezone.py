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
        database.DB_PATH = Path(tmp) / "profile_timezone.db"
        database.init_db()

        import app.auth as auth
        import app.server as server

        user = auth.create_user("tz_user", "password123", "TZ User")
        user_id = int(user["id"])

        result = server.update_profile(
            server.ProfileUpdateRequest(nickname="TZ User", timezone="Asia/Tokyo"),
            user,
        )
        assert result["profile"]["timezone"] == "Asia/Tokyo"

        with database.get_db() as db:
            stored = db.execute("SELECT timezone FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
            assert stored["timezone"] == "Asia/Tokyo"

        try:
            server.update_profile(server.ProfileUpdateRequest(timezone="Mars/Olympus"), user)
            raise AssertionError("invalid timezone must fail")
        except server.HTTPException as exc:
            assert exc.status_code == 400
            assert exc.detail == "invalid timezone"

        cleared = server.update_profile(server.ProfileUpdateRequest(timezone=""), user)
        assert cleared["profile"]["timezone"] == ""

    print("Profile timezone verification passed")


if __name__ == "__main__":
    main()
