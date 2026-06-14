from __future__ import annotations

import sys
import tempfile
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app.database as database


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        database.DB_PATH = Path(tmp) / "self_use.db"
        database.init_db()

        import app.auth as auth
        import app.server as server

        first = auth.get_or_create_local_user("mio_owner", "Mio")
        second = auth.get_or_create_local_user("mio_owner", "澪的工作区")

        assert first["id"] == second["id"]
        assert second["username"] == "mio_owner"
        assert second["role"] == "admin"
        assert second["status"] == "active"
        assert not second["is_guest"]

        with database.get_db() as db:
            assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
            profile = db.execute("SELECT * FROM user_profiles WHERE user_id = ?", (second["id"],)).fetchone()
            assert profile is not None
            assert profile["nickname"] == "澪的工作区"

        config = {
            "seed_default_persona": True,
            "default_persona_name": "澪",
        }
        persona = server._ensure_self_use_default_persona(int(second["id"]), config)
        repeated = server._ensure_self_use_default_persona(int(second["id"]), config)

        assert persona is not None
        assert repeated is not None
        assert persona["id"] == repeated["id"]
        assert persona["name"] == "澪"
        assert persona["summary"] == "基础设定待填写。"
        assert persona["relationship"] == "未设定"
        assert persona["speaking_style"] == ""
        assert persona["appearance_description"] == ""
        assert persona["desired_image"] == ""
        assert persona["growth_notes"] == ""
        assert json.loads(persona["traits_json"]) == []
        assert json.loads(persona["boundaries_json"]) == []

        with database.get_db() as db:
            assert db.execute("SELECT COUNT(*) FROM personas WHERE user_id = ?", (second["id"],)).fetchone()[0] == 1
            version = db.execute("SELECT * FROM persona_versions WHERE persona_id = ?", (persona["id"],)).fetchone()
            assert version is not None
            assert version["change_type"] == "self_use_default"

        with database.get_db() as db:
            db.execute(
                """
                UPDATE personas
                SET summary = ?, relationship = ?, speaking_style = ?, appearance_description = ?,
                    traits_json = ?, boundaries_json = ?
                WHERE id = ?
                """,
                (
                    "一个以 Live2D 形象在场的长期陪伴体，安静、机敏、低压迫，重视真实相处中的节奏和边界。",
                    "自用长期陪伴体",
                    "自然短句，少说教，不把自己讲成工具。",
                    "Live2D / AI VTB 形象优先",
                    '["在场感", "低压迫", "机敏"]',
                    '["不把登录、群聊、人格列表当作核心体验扩张。"]',
                    persona["id"],
                ),
            )
            db.execute(
                """
                UPDATE persona_versions
                SET change_type = 'self_use_default'
                WHERE persona_id = ? AND version = 1
                """,
                (persona["id"],),
            )
        cleared = server._ensure_self_use_default_persona(int(second["id"]), config)
        assert cleared is not None
        assert cleared["summary"] == "基础设定待填写。"
        assert cleared["relationship"] == "未设定"
        assert cleared["speaking_style"] == ""
        assert json.loads(cleared["traits_json"]) == []

        from fastapi import HTTPException
        from fastapi import BackgroundTasks

        public_self_use = server._self_use_public(second)
        assert public_self_use["enabled"] is True
        assert public_self_use["chat_enabled"] is False

        try:
            server.create_persona(
                server.PersonaCreateRequest(description="should not create another companion"),
                second,
            )
            raise AssertionError("self-use mode should reject persona generation")
        except HTTPException as exc:
            assert exc.status_code == 403
            assert "self-use mode" in str(exc.detail)

        try:
            server.chat(
                server.ChatRequest(message="hello", persona_id=int(cleared["id"])),
                BackgroundTasks(),
                second,
            )
            raise AssertionError("self-use mode should reject chat until explicitly enabled")
        except HTTPException as exc:
            assert exc.status_code == 403
            assert "chat is not enabled" in str(exc.detail)

    print("Self-use local login verification passed")


if __name__ == "__main__":
    main()
