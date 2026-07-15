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
        database.DB_PATH = Path(tmp) / "companion_status.db"
        database.init_db()

        import app.auth as auth
        import app.server as server
        from fastapi import HTTPException

        original_load_config = server.load_config
        original_llm_runtime_status = server.llm_runtime_status
        original_get_video_status = server.get_video_companion_status
        original_load_live2d_config = server.load_live2d_config
        original_live2d_enabled = server.live2d_enabled
        original_live2d_connection_status = server.live2d_connection_status
        original_load_voice_config = server.load_voice_config
        original_voice_enabled = server.voice_enabled
        original_tts_health_check = server.tts_health_check
        try:
            server.load_config = lambda: {
                "self_use": {
                    "enabled": True,
                    "chat_enabled": False,
                    "seed_default_persona": True,
                    "default_persona_name": "Mio",
                    "username": "mio_owner",
                }
            }
            server.llm_runtime_status = lambda task="chat": {
                "task": task,
                "provider": "kimi",
                "model": "kimi-k2.6",
                "api_key_env": "MOONSHOT_API_KEY",
                "requires_api_key": True,
                "configured": False,
                "verified": False,
                "verification": {"state": "unverified", "checked_at": None},
                "missing": ["MOONSHOT_API_KEY"],
            }
            server.get_video_companion_status = lambda: {
                "enabled": False,
                "connected": False,
                "reason": "video_companion_disabled",
                "config": {"enabled": False},
            }
            server.load_live2d_config = lambda: {
                "enabled": False,
                "idle_expressions": ["Neutral"],
                "listening_expression": "Listen",
                "speaking_expression": "Talk",
                "thinking_expression": "Think",
                "expression_map": {"happy": "Smile"},
            }
            server.live2d_enabled = lambda: False
            server.live2d_connection_status = lambda: {
                "enabled": False,
                "connected": False,
                "authenticated": False,
                "last_error": None,
                "current_model": {},
            }
            server.load_voice_config = lambda: {"enabled": False}
            server.voice_enabled = lambda: False
            server.tts_health_check = lambda: {
                "enabled": False,
                "provider": "openai_tts",
                "voice_id": "alloy",
                "available": False,
                "error": "voice is disabled in config",
            }

            user = auth.get_or_create_local_user("mio_owner", "Mio")
            persona = server._ensure_self_use_default_persona(
                int(user["id"]),
                {
                    "seed_default_persona": True,
                    "default_persona_name": "Mio",
                },
            )
            assert persona is not None

            status = server.companion_status(user)
            assert status["self_use"]["enabled"] is True
            assert status["self_use"]["chat_enabled"] is False
            assert status["persona_id"] == persona["id"]
            assert status["runtime"]["key"] == "offline"
            assert status["runtime"]["ready"] is False
            assert status["chat_gate"]["enabled"] is False
            assert status["chat_gate"]["ready"] is False
            assert status["chat_gate"]["can_enable"] is False
            assert status["chat_gate"]["reason"] == "missing_api_key"
            assert status["chat_gate"]["missing"] == ["MOONSHOT_API_KEY"]
            assert status["ready_count"] == 0
            assert status["total_count"] == 4
            assert status["optional_ready_count"] == 0
            assert status["optional_total_count"] == 2
            assert {item["key"] for item in status["readiness"]} == {
                "api", "visual", "live2d", "voice", "lip_sync", "video"
            }
            assert status["live2d_actions"]["idle_expression"] == "Neutral"
            assert status["live2d_actions"]["listening_expression"] == "Listen"
            assert status["live2d_actions"]["speaking_expression"] == "Talk"
            assert status["live2d_actions"]["thinking_expression"] == "Think"
            assert status["live2d_actions"]["expression_map_count"] == 1
            assert status["live2d_actions"]["expression_map"]["happy"] == "Smile"
            assert status["voice"]["available"] is False
            readiness = {item["key"]: item for item in status["readiness"]}
            assert readiness["api"]["ready"] is False
            assert "缺少 MOONSHOT_API_KEY" in readiness["api"]["text"]
            assert readiness["visual"]["ready"] is False
            assert "未绑定 Live2D preview" in readiness["visual"]["text"]
            assert readiness["live2d"]["ready"] is False
            assert readiness["voice"]["ready"] is False
            assert readiness["voice"]["text"] == "Voice profile unbound"
            assert readiness["lip_sync"]["ready"] is False
            assert readiness["video"]["ready"] is False
            assert readiness["visual"]["required"] is False
            assert readiness["video"]["required"] is False
            assert all(readiness[key]["required"] for key in ("api", "live2d", "voice", "lip_sync"))
            assert status["embodiment"]["live2d_bound"] is False
            assert status["embodiment"]["voice_bound"] is False
            assert status["embodiment"]["visual_label"] == "临时形象待绑定"
            assert status["embodiment"]["visual_tone"] == "missing"

            with database.get_db() as db:
                db.execute(
                    """
                    UPDATE personas
                    SET live2d_model_id = ?, live2d_preview_url = ?, voice_profile = ?
                    WHERE id = ?
                    """,
                    ("mio-main", "/uploads/mio-preview.webp", "mio-soft-v1", persona["id"]),
                )
                extra_id = db.execute(
                    """
                    INSERT INTO personas (
                        user_id, name, summary, prompt, traits_json, relationship,
                        speaking_style, boundaries_json, created_at, updated_at
                    )
                    VALUES (?, 'Legacy Extra', 'hidden', 'hidden prompt', '[]', '',
                            '', '[]', ?, ?)
                    """,
                    (user["id"], database.now_ts(), database.now_ts()),
                ).lastrowid

            asset_status = server.companion_status(user)
            assert asset_status["embodiment"]["live2d_model_id"] == "mio-main"
            assert asset_status["embodiment"]["visual_url"] == "/uploads/mio-preview.webp"
            assert asset_status["embodiment"]["visual_source"] == "live2d_preview_url"
            assert asset_status["embodiment"]["visual_label"] == "临时静态形象"
            assert asset_status["embodiment"]["visual_tone"] == "preview"
            assert asset_status["embodiment"]["visual_ready"] is True
            assert asset_status["embodiment"]["voice_profile"] == "mio-soft-v1"
            asset_readiness = {item["key"]: item for item in asset_status["readiness"]}
            assert asset_readiness["visual"]["ready"] is True
            assert asset_readiness["visual"]["text"] == "临时静态形象"
            assert asset_readiness["live2d"]["ready"] is False
            assert "适配器未启用" in asset_readiness["live2d"]["text"]
            assert asset_readiness["voice"]["ready"] is False
            assert "TTS 未启用" in asset_readiness["voice"]["text"]

            with database.get_db() as db:
                db.execute(
                    """
                    UPDATE personas
                    SET live2d_preview_url = '', fallback_image_url = '', avatar_url = ?
                    WHERE id = ?
                    """,
                    ("/uploads/legacy-avatar.webp", persona["id"]),
                )
            legacy_visual_status = server.companion_status(user)
            assert legacy_visual_status["embodiment"]["visual_url"] == "/uploads/legacy-avatar.webp"
            assert legacy_visual_status["embodiment"]["visual_source"] == "avatar_url"
            assert legacy_visual_status["embodiment"]["visual_label"] == "Legacy avatar fallback"
            assert legacy_visual_status["embodiment"]["visual_tone"] == "legacy"
            assert legacy_visual_status["embodiment"]["visual_ready"] is False
            legacy_readiness = {item["key"]: item for item in legacy_visual_status["readiness"]}
            assert legacy_readiness["visual"]["ready"] is False
            assert "旧头像 fallback" in legacy_readiness["visual"]["text"]

            with database.get_db() as db:
                db.execute(
                    """
                    UPDATE personas
                    SET live2d_preview_url = ?, avatar_url = ''
                    WHERE id = ?
                    """,
                    ("/uploads/mio-preview.webp", persona["id"]),
                )

            server.load_config = lambda: {
                "self_use": {
                    "enabled": True,
                    "chat_enabled": True,
                    "seed_default_persona": True,
                    "default_persona_name": "Mio",
                    "username": "mio_owner",
                }
            }
            server.llm_runtime_status = lambda task="chat": {
                "task": task,
                "provider": "ollama",
                "model": "qwen2.5:3b",
                "api_key_env": "",
                "requires_api_key": False,
                "configured": True,
                "verified": True,
                "verification": {"state": "verified", "checked_at": 123},
                "missing": [],
            }
            server.load_live2d_config = lambda: {
                "enabled": True,
                "lip_sync_enabled": True,
                "lip_sync_parameter": "MouthOpen",
                "lip_sync_gain": 2.2,
                "idle_expressions": ["Idle"],
                "listening_expression": "Listening",
                "speaking_expression": "Talking",
                "thinking_expression": "Thinking",
                "expression_map": {"sad": "Sad"},
            }
            server.live2d_enabled = lambda: True
            server.live2d_connection_status = lambda: {
                "enabled": True,
                "connected": True,
                "authenticated": True,
                "last_error": None,
                "capabilities_stale": False,
                "available_parameters": [{"name": "MouthOpen"}],
                "current_model": {
                    "modelLoaded": True,
                    "modelID": "mio-main",
                    "modelName": "Mio Main",
                },
            }
            server.load_voice_config = lambda: {"enabled": True}
            server.voice_enabled = lambda: True
            server.tts_health_check = lambda: {
                "enabled": True,
                "provider": "openai_tts",
                "voice_id": "mio-soft-v1",
                "available": False,
                "error": "missing API key environment variable: OPENAI_API_KEY",
            }
            server.get_video_companion_status = lambda: {
                "enabled": True,
                "connected": True,
                "config": {"enabled": True},
            }
            ready_status = server.companion_status(user)
            assert ready_status["chat_gate"]["enabled"] is True
            assert ready_status["chat_gate"]["ready"] is True
            assert ready_status["chat_gate"]["reason"] == "ready"
            assert ready_status["chat_gate"]["provider"] == "ollama"
            assert ready_status["ready_count"] == 3
            assert ready_status["optional_ready_count"] == 2
            assert not all(item["ready"] for item in ready_status["readiness"])
            assert ready_status["runtime"]["key"] == "present"
            assert ready_status["live2d"]["current_model"]["modelID"] == "mio-main"
            assert ready_status["live2d_actions"]["listening_expression"] == "Listening"
            assert ready_status["live2d_actions"]["speaking_expression"] == "Talking"
            assert ready_status["live2d_actions"]["expression_map_count"] == 1
            assert ready_status["voice"]["available"] is False
            ready_items = {item["key"]: item for item in ready_status["readiness"]}
            assert ready_items["voice"]["ready"] is False
            assert ready_items["lip_sync"]["ready"] is True
            assert "MouthOpen" in ready_items["lip_sync"]["text"]

            server.live2d_connection_status = lambda: {
                "enabled": True,
                "connected": True,
                "authenticated": True,
                "last_error": None,
                "capabilities_stale": False,
                "available_parameters": [{"name": "MouthOpen"}],
                "current_model": {
                    "modelLoaded": True,
                    "modelID": "another-model",
                    "modelName": "Another Model",
                },
            }
            mismatch_status = server.companion_status(user)
            mismatch_live2d = {item["key"]: item for item in mismatch_status["readiness"]}["live2d"]
            assert mismatch_live2d["ready"] is False
            assert "不一致" in mismatch_live2d["text"]
            assert mismatch_status["runtime"]["key"] == "waiting"
            assert mismatch_status["runtime"]["ready"] is False
            try:
                server._require_self_use_live2d_ready(user)
                raise AssertionError("mismatched VTube Studio model must not accept LING actions")
            except HTTPException as exc:
                assert exc.status_code == 409
                assert "不一致" in str(exc.detail)

            server.live2d_connection_status = lambda: {
                "enabled": True,
                "connected": True,
                "authenticated": True,
                "last_error": None,
                "capabilities_stale": False,
                "available_parameters": [{"name": "MouthOpen"}],
                "current_model": {
                    "modelLoaded": True,
                    "modelID": "mio-main",
                    "modelName": "Mio Main",
                },
            }
            server._require_self_use_live2d_ready(user)

            server.tts_health_check = lambda: {
                "enabled": True,
                "provider": "dedicated",
                "voice_id": "mio-soft-v1",
                "available": True,
                "error": None,
            }
            ready_voice_status = server.companion_status(user)
            assert ready_voice_status["ready_count"] == 4
            assert {item["key"]: item for item in ready_voice_status["readiness"]}["voice"]["ready"] is True

            try:
                server.companion_status(user, persona_id=int(extra_id))
                raise AssertionError("self-use companion status should hide legacy personas")
            except HTTPException as exc:
                assert exc.status_code == 404
                assert "LING self-use mode" in str(exc.detail)
        finally:
            server.load_config = original_load_config
            server.llm_runtime_status = original_llm_runtime_status
            server.get_video_companion_status = original_get_video_status
            server.load_live2d_config = original_load_live2d_config
            server.live2d_enabled = original_live2d_enabled
            server.live2d_connection_status = original_live2d_connection_status
            server.load_voice_config = original_load_voice_config
            server.voice_enabled = original_voice_enabled
            server.tts_health_check = original_tts_health_check

    print("Companion status verification passed")


if __name__ == "__main__":
    main()
