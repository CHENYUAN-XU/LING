from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from fastapi import Response


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app.database as database


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        database.DB_PATH = root / "account_delete.db"
        uploads = root / "uploads"
        database.init_db()

        import app.auth as auth
        import app.server as server

        auth.UPLOAD_ROOT = uploads
        server.UPLOAD_DIR = uploads

        user = auth.create_user("delete_me", "password123", "Delete Me")
        user_id = int(user["id"])
        upload_dir = uploads / str(user_id)
        upload_dir.mkdir(parents=True)
        (upload_dir / "avatar.txt").write_text("avatar", encoding="utf-8")

        with database.get_db() as db:
            persona_id = int(db.execute(
                """
                INSERT INTO personas (user_id, name, summary, prompt, created_at, updated_at)
                VALUES (?, 'Delete Account Persona', 'summary', 'prompt', ?, ?)
                """,
                (user_id, database.now_ts(), database.now_ts()),
            ).lastrowid)
            db.execute(
                "INSERT INTO conversations (user_id, persona_id, title, created_at, updated_at) VALUES (?, ?, 'account chat', ?, ?)",
                (user_id, persona_id, database.now_ts(), database.now_ts()),
            )

        try:
            server.account_delete(
                server.AccountDeleteRequest(confirm_username="delete_me", password="wrong"),
                Response(),
                user,
            )
            raise AssertionError("wrong password must fail")
        except server.HTTPException as exc:
            assert exc.status_code == 401

        result = server.account_delete(
            server.AccountDeleteRequest(confirm_username="delete_me", password="password123"),
            Response(),
            user,
        )
        assert result["status"] == "deleted"
        assert not upload_dir.exists()

        with database.get_db() as db:
            assert db.execute("SELECT COUNT(*) AS c FROM users WHERE id = ?", (user_id,)).fetchone()["c"] == 0
            assert db.execute("SELECT COUNT(*) AS c FROM personas WHERE user_id = ?", (user_id,)).fetchone()["c"] == 0
            assert db.execute("SELECT COUNT(*) AS c FROM conversations WHERE user_id = ?", (user_id,)).fetchone()["c"] == 0

        guest = auth.create_guest_user()
        guest_id = int(guest["id"])
        guest_upload = uploads / str(guest_id)
        guest_upload.mkdir(parents=True)
        (guest_upload / "guest.txt").write_text("guest", encoding="utf-8")
        guest_result = server.account_delete(
            server.AccountDeleteRequest(confirm_username=str(guest["username"])),
            Response(),
            guest,
        )
        assert guest_result["status"] == "deleted"
        assert not guest_upload.exists()

    print("Account delete verification passed")


if __name__ == "__main__":
    main()
