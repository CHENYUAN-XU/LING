from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app.database as database
from app.user_export import export_user_data, write_user_export


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        database.DB_PATH = root / "export.db"
        uploads = root / "uploads"
        database.init_db()

        ts = database.now_ts()
        with database.get_db() as db:
            user_id = int(db.execute(
                "INSERT INTO users (username, password_hash, created_at, updated_at) VALUES ('export-me', 'secret-hash', ?, ?)",
                (ts, ts),
            ).lastrowid)
            other_id = int(db.execute(
                "INSERT INTO users (username, password_hash, created_at, updated_at) VALUES ('other-user', 'other-hash', ?, ?)",
                (ts, ts),
            ).lastrowid)
            db.execute(
                "INSERT INTO user_profiles (user_id, nickname, created_at, updated_at) VALUES (?, 'Export Me', ?, ?)",
                (user_id, ts, ts),
            )
            db.execute(
                "INSERT INTO user_profiles (user_id, nickname, created_at, updated_at) VALUES (?, 'Other', ?, ?)",
                (other_id, ts, ts),
            )
            persona_id = int(db.execute(
                """
                INSERT INTO personas (user_id, name, summary, prompt, created_at, updated_at)
                VALUES (?, 'Mio Export', 'summary', 'prompt', ?, ?)
                """,
                (user_id, ts, ts),
            ).lastrowid)
            other_persona_id = int(db.execute(
                """
                INSERT INTO personas (user_id, name, summary, prompt, created_at, updated_at)
                VALUES (?, 'Other Persona', 'summary', 'prompt', ?, ?)
                """,
                (other_id, ts, ts),
            ).lastrowid)
            conversation_id = int(db.execute(
                "INSERT INTO conversations (user_id, persona_id, title, created_at, updated_at) VALUES (?, ?, 'Export Chat', ?, ?)",
                (user_id, persona_id, ts, ts),
            ).lastrowid)
            db.execute(
                "INSERT INTO messages (conversation_id, user_id, persona_id, role, content, created_at) VALUES (?, ?, ?, 'user', 'hello export', ?)",
                (conversation_id, user_id, persona_id, ts),
            )
            db.execute(
                "INSERT INTO conversations (user_id, persona_id, title, created_at, updated_at) VALUES (?, ?, 'Other Chat', ?, ?)",
                (other_id, other_persona_id, ts, ts),
            )
            db.execute(
                "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES ('secret-token', ?, ?, ?)",
                (user_id, ts, ts + 100),
            )

        user_upload_dir = uploads / str(user_id)
        other_upload_dir = uploads / str(other_id)
        user_upload_dir.mkdir(parents=True)
        other_upload_dir.mkdir(parents=True)
        (user_upload_dir / "avatar.txt").write_text("mine", encoding="utf-8")
        (other_upload_dir / "avatar.txt").write_text("other", encoding="utf-8")

        exported = export_user_data(user_id, uploads_dir=uploads)
        assert exported["user_id"] == user_id
        assert "sessions" not in exported["tables"]
        assert "password_hash" not in exported["tables"]["users"][0]
        assert exported["tables"]["users"][0]["username"] == "export-me"
        assert all(row["username"] != "other-user" for row in exported["tables"]["users"])
        assert exported["tables"]["personas"][0]["name"] == "Mio Export"
        assert all(row["name"] != "Other Persona" for row in exported["tables"]["personas"])
        assert exported["tables"]["messages"][0]["content"] == "hello export"
        assert exported["uploads"]["file_count"] == 1
        assert exported["uploads"]["files"][0]["relative_path"] == f"{user_id}/avatar.txt"

        out = root / "export.json"
        write_user_export(out, exported)
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert loaded["user_id"] == user_id

        import app.server as server

        api_export = server.account_export({"id": user_id})
        assert api_export["user_id"] == user_id
        assert "sessions" not in api_export["tables"]
        assert "password_hash" not in api_export["tables"]["users"][0]

    print("User export verification passed")


if __name__ == "__main__":
    main()
