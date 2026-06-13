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
        database.DB_PATH = Path(tmp) / "purge.db"
        database.init_db()
        import app.server as server

        ts = database.now_ts()
        with database.get_db() as db:
            user_id = int(db.execute(
                "INSERT INTO users (username, password_hash, created_at, updated_at) VALUES ('purge-user', 'x', ?, ?)",
                (ts, ts),
            ).lastrowid)
            db.execute(
                "INSERT INTO user_profiles (user_id, nickname, created_at, updated_at) VALUES (?, 'purge', ?, ?)",
                (user_id, ts, ts),
            )
            persona_id = int(db.execute(
                """
                INSERT INTO personas (user_id, name, summary, prompt, created_at, updated_at)
                VALUES (?, 'Purge Me', 'summary', 'prompt', ?, ?)
                """,
                (user_id, ts, ts),
            ).lastrowid)
            conversation_id = int(db.execute(
                "INSERT INTO conversations (user_id, persona_id, title, created_at, updated_at) VALUES (?, ?, 'purge chat', ?, ?)",
                (user_id, persona_id, ts, ts),
            ).lastrowid)
            db.execute(
                "INSERT INTO messages (conversation_id, user_id, persona_id, role, content, created_at) VALUES (?, ?, ?, 'user', 'hello', ?)",
                (conversation_id, user_id, persona_id, ts),
            )

        user = {"id": user_id}
        try:
            server.purge_persona(persona_id, server.PersonaDeleteRequest(confirm_name="Purge Me"), user)
            raise AssertionError("active persona must not be purged directly")
        except server.HTTPException as exc:
            assert exc.status_code == 400

        server.delete_persona(persona_id, server.PersonaDeleteRequest(confirm_name="Purge Me"), user)
        try:
            server.purge_persona(persona_id, server.PersonaDeleteRequest(confirm_name="wrong"), user)
            raise AssertionError("wrong confirmation must fail")
        except server.HTTPException as exc:
            assert exc.status_code == 400

        result = server.purge_persona(persona_id, server.PersonaDeleteRequest(confirm_name="Purge Me"), user)
        assert result["status"] == "purged"

        with database.get_db() as db:
            assert db.execute("SELECT COUNT(*) AS c FROM personas WHERE id = ?", (persona_id,)).fetchone()["c"] == 0
            assert db.execute("SELECT COUNT(*) AS c FROM conversations WHERE persona_id = ?", (persona_id,)).fetchone()["c"] == 0
            assert db.execute("SELECT COUNT(*) AS c FROM messages WHERE persona_id = ?", (persona_id,)).fetchone()["c"] == 0

        try:
            server.restore_persona(persona_id, user)
            raise AssertionError("purged persona must not restore")
        except server.HTTPException as exc:
            assert exc.status_code == 404

    print("Persona purge verification passed")


if __name__ == "__main__":
    main()
