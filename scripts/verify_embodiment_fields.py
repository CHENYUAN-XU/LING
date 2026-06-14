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
        database.DB_PATH = Path(tmp) / "embodiment_fields.db"
        database.init_db()

        import app.auth as auth
        import app.server as server
        from fastapi import HTTPException

        user = auth.create_user("embodiment_user", "password123", "Embodiment User")
        ts = database.now_ts()
        with database.get_db() as db:
            cursor = db.execute(
                """
                INSERT INTO personas (user_id, name, summary, prompt, relationship, speaking_style, created_at, updated_at)
                VALUES (?, 'Mio', 'blank', 'prompt', 'unset', '', ?, ?)
                """,
                (user["id"], ts, ts),
            )
            persona_id = int(cursor.lastrowid)

        original = server.personas(user)["personas"][0]
        original_version = int(original["version"])
        assert original["live2d_model_id"] == ""
        assert original["live2d_preview_url"] == ""
        assert original["fallback_image_url"] == ""
        assert original["voice_profile"] == ""

        updated = server.update_persona(
            persona_id,
            server.PersonaUpdateRequest(
                live2d_model_id="mio-main",
                live2d_preview_url="/uploads/1/mio-preview.webp",
                fallback_image_url="https://example.com/mio-fallback.png",
                voice_profile="mio-soft-v1",
            ),
            user,
        )["persona"]

        assert updated["live2d_model_id"] == "mio-main"
        assert updated["live2d_preview_url"] == "/uploads/1/mio-preview.webp"
        assert updated["fallback_image_url"] == "https://example.com/mio-fallback.png"
        assert updated["voice_profile"] == "mio-soft-v1"
        assert int(updated["version"]) == original_version, "asset-only updates must not grow persona version"

        embodiment = server.persona_embodiment(persona_id, user)["embodiment"]
        assert embodiment["live2d_model_id"] == "mio-main"
        assert embodiment["visual_url"] == "/uploads/1/mio-preview.webp"
        assert embodiment["visual_source"] == "live2d_preview_url"
        assert embodiment["voice_profile"] == "mio-soft-v1"
        assert embodiment["live2d_bound"] is True
        assert embodiment["visual_ready"] is True
        assert embodiment["voice_bound"] is True

        from app.video_bridge import build_video_session_context

        video_context = build_video_session_context(persona_id)
        video_embodiment = video_context["persona_public_info"]["embodiment"]
        assert video_embodiment["live2d_model_id"] == "mio-main"
        assert video_embodiment["visual_url"] == "/uploads/1/mio-preview.webp"
        assert video_embodiment["voice_profile"] == "mio-soft-v1"

        with database.get_db() as db:
            row = db.execute("SELECT * FROM personas WHERE id = ?", (persona_id,)).fetchone()
            assert row["live2d_model_id"] == "mio-main"
            assert row["live2d_preview_url"] == "/uploads/1/mio-preview.webp"
            assert row["fallback_image_url"] == "https://example.com/mio-fallback.png"
            assert row["voice_profile"] == "mio-soft-v1"

        try:
            server.update_persona(
                persona_id,
                server.PersonaUpdateRequest(live2d_preview_url="javascript:alert(1)"),
                user,
            )
            raise AssertionError("invalid live2d preview url should be rejected")
        except HTTPException as exc:
            assert exc.status_code == 400
            assert "live2d_preview_url" in str(exc.detail)

        try:
            server.update_persona(
                persona_id,
                server.PersonaUpdateRequest(fallback_image_url="file:///tmp/mio.png"),
                user,
            )
            raise AssertionError("invalid fallback image url should be rejected")
        except HTTPException as exc:
            assert exc.status_code == 400
            assert "fallback_image_url" in str(exc.detail)

    print("Embodiment fields verification passed")


if __name__ == "__main__":
    main()
