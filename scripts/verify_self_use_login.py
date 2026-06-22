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

        first = auth.get_or_create_local_user("mio_owner", "")
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
            assert profile["nickname"] == ""
            db.execute("UPDATE user_profiles SET nickname = 'Yue' WHERE user_id = ?", (second["id"],))

        auth.get_or_create_local_user("mio_owner", "system default must not overwrite")
        with database.get_db() as db:
            profile = db.execute("SELECT * FROM user_profiles WHERE user_id = ?", (second["id"],)).fetchone()
            assert profile["nickname"] == "Yue"
            db.execute("UPDATE user_profiles SET nickname = '澪的工作区' WHERE user_id = ?", (second["id"],))
        server._clear_generated_self_use_profile(int(second["id"]))
        with database.get_db() as db:
            profile = db.execute("SELECT * FROM user_profiles WHERE user_id = ?", (second["id"],)).fetchone()
            assert profile["nickname"] == ""

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
        assert persona["summary"] == ""
        assert persona["relationship"] == ""
        assert persona["speaking_style"] == ""
        assert persona["appearance_description"] == ""
        assert persona["desired_image"] == ""
        assert persona["live2d_model_id"] == ""
        assert persona["live2d_preview_url"] == ""
        assert persona["fallback_image_url"] == ""
        assert persona["voice_profile"] == ""
        assert persona["growth_notes"] == ""
        assert json.loads(persona["traits_json"]) == []
        assert json.loads(persona["boundaries_json"]) == []
        assert "LING 本地工作区中唯一、持续存在的 AI companion" in persona["prompt"]
        assert "用户创建的长期对话对象" not in persona["prompt"]
        assert "群聊成员" in persona["prompt"]

        with database.get_db() as db:
            assert db.execute("SELECT COUNT(*) FROM personas WHERE user_id = ?", (second["id"],)).fetchone()[0] == 1
            binding = db.execute(
                "SELECT persona_id FROM self_use_companion_bindings WHERE user_id = ?",
                (second["id"],),
            ).fetchone()
            assert binding is not None
            assert int(binding["persona_id"]) == int(persona["id"])
            version = db.execute("SELECT * FROM persona_versions WHERE persona_id = ?", (persona["id"],)).fetchone()
            assert version is not None
            assert version["change_type"] == "self_use_default"

        server._normalize_existing_persona_identity()
        with database.get_db() as db:
            normalized_persona = db.execute("SELECT prompt FROM personas WHERE id = ?", (persona["id"],)).fetchone()
            normalized_version = db.execute(
                "SELECT prompt FROM persona_versions WHERE persona_id = ? ORDER BY version DESC LIMIT 1",
                (persona["id"],),
            ).fetchone()
        assert "LING 本地工作区中唯一、持续存在的 AI companion" in normalized_persona["prompt"]
        assert "LING 本地工作区中唯一、持续存在的 AI companion" in normalized_version["prompt"]
        assert "用户创建的长期对话对象" not in normalized_persona["prompt"]

        multi = auth.get_or_create_local_user("mio_owner_multi", "Mio Multi")
        with database.get_db() as db:
            ts = database.now_ts()
            first_legacy_id = db.execute(
                """
                INSERT INTO personas (
                    user_id, name, summary, prompt, traits_json, relationship,
                    speaking_style, boundaries_json, created_at, updated_at
                )
                VALUES (?, 'Legacy One', 'legacy one', 'legacy prompt', '[]', '',
                        '', '[]', ?, ?)
                """,
                (multi["id"], ts, ts),
            ).lastrowid
            db.execute(
                """
                INSERT INTO personas (
                    user_id, name, summary, prompt, traits_json, relationship,
                    speaking_style, boundaries_json, created_at, updated_at
                )
                VALUES (?, 'Legacy Two', 'legacy two', 'legacy prompt', '[]', '',
                        '', '[]', ?, ?)
                """,
                (multi["id"], ts + 1, ts + 1),
            )
        multi_companion = server._ensure_self_use_default_persona(int(multi["id"]), config)
        assert multi_companion is not None
        assert multi_companion["name"] == "澪"
        assert multi_companion["id"] != first_legacy_id
        with database.get_db() as db:
            assert db.execute("SELECT COUNT(*) FROM personas WHERE user_id = ?", (multi["id"],)).fetchone()[0] == 3
            db.execute("UPDATE personas SET name = 'Mio Renamed' WHERE id = ?", (multi_companion["id"],))

        renamed_companion = server._ensure_self_use_default_persona(int(multi["id"]), config)
        assert renamed_companion is not None
        assert renamed_companion["id"] == multi_companion["id"]
        assert renamed_companion["name"] == "Mio Renamed"
        assert "名字：Mio Renamed" in renamed_companion["prompt"]

        original_load_config = server.load_config
        try:
            server.load_config = lambda: {
                "self_use": {
                    "enabled": True,
                    "username": "mio_owner_multi",
                    "chat_enabled": False,
                    "seed_default_persona": True,
                    "default_persona_name": "澪",
                }
            }
            assert server._self_use_bound_persona_id(multi) == multi_companion["id"]
        finally:
            server.load_config = original_load_config

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
        assert cleared["summary"] == ""
        assert cleared["relationship"] == ""
        assert cleared["speaking_style"] == ""
        assert json.loads(cleared["traits_json"]) == []
        assert "未填写表示尚未确定" in cleared["prompt"]

        repeated_blank = server._ensure_self_use_default_persona(int(second["id"]), config)
        assert repeated_blank is not None
        assert repeated_blank["version"] == cleared["version"]

        from fastapi import HTTPException
        from fastapi import BackgroundTasks

        with database.get_db() as db:
            ts = database.now_ts()
            extra_id = db.execute(
                """
                INSERT INTO personas (
                    user_id, name, summary, prompt, traits_json, relationship,
                    speaking_style, boundaries_json, created_at, updated_at
                )
                VALUES (?, 'Legacy Extra', 'legacy summary', 'legacy prompt', '[]', '',
                        '', '[]', ?, ?)
                """,
                (second["id"], ts, ts),
            ).lastrowid
            bound_conversation_id = db.execute(
                """
                INSERT INTO conversations (user_id, persona_id, title, created_at, updated_at)
                VALUES (?, ?, 'Bound conversation', ?, ?)
                """,
                (second["id"], cleared["id"], ts, ts),
            ).lastrowid
            extra_conversation_id = db.execute(
                """
                INSERT INTO conversations (user_id, persona_id, title, created_at, updated_at)
                VALUES (?, ?, 'Legacy conversation', ?, ?)
                """,
                (second["id"], extra_id, ts, ts),
            ).lastrowid
            db.execute(
                """
                INSERT INTO messages (conversation_id, user_id, persona_id, role, content, created_at)
                VALUES (?, ?, ?, 'user', 'legacy message', ?)
                """,
                (extra_conversation_id, second["id"], extra_id, ts),
            )

        public_self_use = server._self_use_public(second)
        assert public_self_use["enabled"] is True
        assert public_self_use["chat_enabled"] is False
        assert [item["id"] for item in server.personas(second)["personas"]] == [cleared["id"]]
        assert server.deleted_personas(second)["personas"] == []

        try:
            server.persona_detail(int(extra_id), second)
            raise AssertionError("self-use mode should hide legacy personas")
        except HTTPException as exc:
            assert exc.status_code == 404

        try:
            server.persona_embodiment(int(extra_id), second)
            raise AssertionError("self-use mode should hide legacy embodiment profiles")
        except HTTPException as exc:
            assert exc.status_code == 404

        try:
            server.update_persona(
                int(extra_id),
                server.PersonaUpdateRequest(summary="should not update legacy persona"),
                second,
            )
            raise AssertionError("self-use mode should reject updating legacy personas")
        except HTTPException as exc:
            assert exc.status_code == 404

        conversations = server.conversations(second)["conversations"]
        assert [item["id"] for item in conversations] == [bound_conversation_id]

        try:
            server.conversation_messages(int(extra_conversation_id), second)
            raise AssertionError("self-use mode should hide legacy conversation messages")
        except HTTPException as exc:
            assert exc.status_code == 404

        try:
            server.mark_conversation_read(int(extra_conversation_id), second)
            raise AssertionError("self-use mode should reject marking legacy conversations read")
        except HTTPException as exc:
            assert exc.status_code == 404

        try:
            server.update_conversation(
                int(extra_conversation_id),
                server.ConversationUpdateRequest(title="hidden"),
                second,
            )
            raise AssertionError("self-use mode should reject updating legacy conversations")
        except HTTPException as exc:
            assert exc.status_code == 404

        try:
            server.chat(
                server.ChatRequest(message="hello", persona_id=int(extra_id)),
                BackgroundTasks(),
                second,
            )
            raise AssertionError("self-use mode should reject chat with legacy persona ids")
        except HTTPException as exc:
            assert exc.status_code == 404

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
            server.delete_persona(
                int(cleared["id"]),
                server.PersonaDeleteRequest(confirm_name=str(cleared["name"])),
                second,
            )
            raise AssertionError("self-use mode should reject deleting the bound companion")
        except HTTPException as exc:
            assert exc.status_code == 403
            assert "single companion" in str(exc.detail)

        try:
            from fastapi import Response

            server.account_delete(
                server.AccountDeleteRequest(confirm_username="mio_owner", password="unknown"),
                Response(),
                second,
            )
            raise AssertionError("self-use mode should not expose account deletion for the internal owner")
        except HTTPException as exc:
            assert exc.status_code == 403
            assert "export and backup" in str(exc.detail)

        try:
            server.restore_persona(int(extra_id), second)
            raise AssertionError("self-use mode should reject restoring legacy personas")
        except HTTPException as exc:
            assert exc.status_code == 403
            assert "legacy personas" in str(exc.detail)

        assert server.group_conversations(second)["group_conversations"] == []

        try:
            server.create_group_conversation_endpoint(
                server.GroupConversationCreateRequest(title="should not exist", persona_ids=[int(cleared["id"]), int(cleared["id"])]),
                second,
            )
            raise AssertionError("self-use mode should reject group conversation creation")
        except HTTPException as exc:
            assert exc.status_code == 403
            assert "group conversations" in str(exc.detail)

        try:
            server.group_chat_endpoint(
                server.GroupChatRequest(message="hello group", group_conversation_id=1),
                second,
            )
            raise AssertionError("self-use mode should reject group chat")
        except HTTPException as exc:
            assert exc.status_code == 403
            assert "group conversations" in str(exc.detail)

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

        from fastapi.testclient import TestClient

        original_is_local_request = server._is_local_request
        try:
            server._is_local_request = lambda request: True
            with TestClient(server.app) as client:
                local_login = client.post("/api/auth/local")
                assert local_login.status_code == 200
                payload = local_login.json()
                assert payload["user"]["username"] == "mio_owner"
                assert payload["self_use"]["enabled"] is True
                assert payload["self_use"]["chat_enabled"] is False
                me = client.get("/api/me")
                assert me.status_code == 200
                assert me.json()["self_use"]["enabled"] is True

                legacy_auth_requests = [
                    client.post(
                        "/api/auth/register",
                        json={"username": "legacy-new", "password": "password123"},
                    ),
                    client.post(
                        "/api/auth/login",
                        json={"username": "mio_owner", "password": "password123"},
                    ),
                    client.post("/api/auth/guest"),
                    client.post(
                        "/api/auth/guest/convert",
                        json={"username": "legacy-convert", "password": "password123"},
                    ),
                ]
                assert all(response.status_code == 404 for response in legacy_auth_requests)
                assert all("local owner authentication" in response.json()["detail"] for response in legacy_auth_requests)

                owner_avatar = client.put("/api/profile", json={"avatar_url": "https://example.com/owner.png"})
                assert owner_avatar.status_code == 400
                assert "owner avatar" in owner_avatar.json()["detail"]

                companion_avatar = client.patch(
                    f"/api/personas/{cleared['id']}",
                    json={"avatar_url": "https://example.com/companion.png"},
                )
                assert companion_avatar.status_code == 400
                assert "avatar_url" in companion_avatar.json()["detail"]
        finally:
            server._is_local_request = original_is_local_request

    print("Self-use local login verification passed")


if __name__ == "__main__":
    main()
