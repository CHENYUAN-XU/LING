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
        database.DB_PATH = Path(tmp) / "avatar-url.db"
        database.init_db()

        import app.auth as auth
        import app.server as server

        user = auth.create_user("avatar_url_user", "password123", "Avatar URL")
        user_id = int(user["id"])
        ts = database.now_ts()
        with database.get_db() as db:
            persona_id = int(
                db.execute(
                    """
                    INSERT INTO personas (user_id, name, summary, prompt, relationship, speaking_style, created_at, updated_at)
                    VALUES (?, 'Link', '头像链接测试', '自然聊天', '关系未定', '短句', ?, ?)
                    """,
                    (user_id, ts, ts),
                ).lastrowid
            )

        profile = server.update_profile(
            server.ProfileUpdateRequest(avatar_url="/uploads/1/avatar.png"),
            user,
        )
        assert profile["profile"]["avatar_url"] == "/uploads/1/avatar.png"

        persona = server.update_persona(
            persona_id,
            server.PersonaUpdateRequest(avatar_url="https://example.com/avatar.webp"),
            user,
        )
        assert persona["persona"]["avatar_url"] == "https://example.com/avatar.webp"

        for bad_url in ("javascript:alert(1)", "data:image/svg+xml,evil", "https://example.com/a b.png"):
            try:
                server.update_profile(server.ProfileUpdateRequest(avatar_url=bad_url), user)
            except server.HTTPException as exc:
                assert exc.status_code == 400
                assert exc.detail == "invalid avatar url"
            else:
                raise AssertionError(f"invalid profile avatar URL accepted: {bad_url}")

            try:
                server.update_persona(persona_id, server.PersonaUpdateRequest(avatar_url=bad_url), user)
            except server.HTTPException as exc:
                assert exc.status_code == 400
                assert exc.detail == "invalid avatar url"
            else:
                raise AssertionError(f"invalid persona avatar URL accepted: {bad_url}")

    print("Avatar URL verification passed")


if __name__ == "__main__":
    main()
