from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app.database as database
import app.server as server


def seed_user() -> int:
    ts = database.now_ts()
    with database.get_db() as db:
        user_id = int(
            db.execute(
                "INSERT INTO users (username, password_hash, created_at, updated_at) VALUES ('video-adapter', 'x', ?, ?)",
                (ts, ts),
            ).lastrowid
        )
        db.execute(
            "INSERT INTO user_profiles (user_id, nickname, created_at, updated_at) VALUES (?, 'video_adapter', ?, ?)",
            (user_id, ts, ts),
        )
    return user_id


def seed_persona(user_id: int) -> int:
    ts = database.now_ts()
    with database.get_db() as db:
        persona_id = int(
            db.execute(
                """
                INSERT INTO personas (
                    user_id, name, summary, prompt, relationship, speaking_style,
                    boundaries_json, created_at, updated_at
                )
                VALUES (?, 'Mio', 'A warm companion.', 'Speak naturally.', 'friend', 'short and gentle', ?, ?, ?)
                """,
                (user_id, '["no fake memories"]', ts, ts),
            ).lastrowid
        )
    return persona_id


def verify_disabled_defaults(user_id: int) -> None:
    import app.video_companion as vc

    user = {"id": user_id}
    assert vc.video_companion_enabled() is False
    cfg = vc.public_video_companion_config()
    assert cfg["enabled"] is False
    assert cfg["base_url"] == "http://127.0.0.1:8782"
    assert cfg["ws_url"] == "ws://127.0.0.1:8782/ws"
    assert cfg["project_path"].endswith("video-companion")
    assert "project_path_exists" in cfg

    server_cfg = server.video_companion_config(user)
    assert server_cfg["video_companion"]["enabled"] is False
    assert "project_path_exists" in server_cfg["video_companion"]

    status = server.video_companion_status(user)
    assert status["enabled"] is False
    assert status["connected"] is False
    assert status["reason"] == "video_companion_disabled"

    start = server.video_companion_start(server.VideoCompanionSessionRequest(persona_id=123), user)
    assert start["started"] is False
    assert start["reason"] == "video_companion_disabled"

    stop = server.video_companion_stop(user)
    assert stop["stopped"] is False
    assert stop["reason"] == "video_companion_disabled"


def verify_env_overrides() -> None:
    import app.video_companion as vc

    keys = [
        "MNEMOSYNE_VIDEO_COMPANION_ENABLED",
        "MNEMOSYNE_VIDEO_COMPANION_BASE_URL",
        "MNEMOSYNE_VIDEO_COMPANION_WS_URL",
        "MNEMOSYNE_VIDEO_COMPANION_PROJECT_PATH",
        "MNEMOSYNE_VIDEO_COMPANION_TIMEOUT_SECONDS",
    ]
    original_env = {key: os.environ.get(key) for key in keys}
    try:
        os.environ["MNEMOSYNE_VIDEO_COMPANION_ENABLED"] = "true"
        os.environ["MNEMOSYNE_VIDEO_COMPANION_BASE_URL"] = "http://127.0.0.1:8892"
        os.environ["MNEMOSYNE_VIDEO_COMPANION_WS_URL"] = "ws://127.0.0.1:8892/ws"
        os.environ["MNEMOSYNE_VIDEO_COMPANION_PROJECT_PATH"] = r"E:\visual-test\video-companion"
        os.environ["MNEMOSYNE_VIDEO_COMPANION_TIMEOUT_SECONDS"] = "7"

        cfg = vc.load_video_companion_config()
        assert cfg["enabled"] is True
        assert cfg["base_url"] == "http://127.0.0.1:8892"
        assert cfg["ws_url"] == "ws://127.0.0.1:8892/ws"
        assert cfg["project_path"].endswith("video-companion")
        assert cfg["timeout_seconds"] == 7.0
    finally:
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def verify_enabled_adapter_flow(user_id: int) -> None:
    import app.video_companion as vc

    original_config = vc.load_config
    original_request = vc._request_json
    calls: list[tuple[str, str, dict | None]] = []

    def fake_config():
        return {
            "video_companion": {
                "enabled": True,
                "base_url": "http://127.0.0.1:8782",
                "ws_url": "ws://127.0.0.1:8782/ws",
                "project_path": r"E:\视觉\video-companion",
                "timeout_seconds": 2,
            }
        }

    def fake_request(method, path, payload=None, *, config=None):
        calls.append((method, path, payload))
        if path == "/api/health":
            return {"ok": True}
        if path == "/api/status":
            return {"session_active": False, "service": "video-companion"}
        if path == "/api/session/start?persona_id=456":
            return {"session_id": "session-1", "persona_id": "456"}
        if path == "/api/session/stop":
            return {"stopped": True}
        raise AssertionError(f"unexpected request: {method} {path}")

    try:
        vc.load_config = fake_config
        vc._request_json = fake_request

        user = {"id": user_id}
        assert vc.video_companion_enabled() is True
        status = server.video_companion_status(user)
        assert status["enabled"] is True
        assert status["connected"] is True
        assert status["health"]["ok"] is True
        assert status["status"]["service"] == "video-companion"

        start = server.video_companion_start(server.VideoCompanionSessionRequest(persona_id=456), user)
        assert start["enabled"] is True
        assert start["started"] is True
        assert start["result"]["persona_id"] == "456"

        stop = server.video_companion_stop(user)
        assert stop["enabled"] is True
        assert stop["stopped"] is True

        assert ("GET", "/api/health", None) in calls
        assert ("GET", "/api/status", None) in calls
        assert ("POST", "/api/session/start?persona_id=456", None) in calls
        assert ("POST", "/api/session/stop", None) in calls
    finally:
        vc.load_config = original_config
        vc._request_json = original_request


def verify_video_bridge_endpoints(user_id: int, persona_id: int) -> None:
    context = server.video_session_context(persona_id)
    assert context["persona_id"] == str(persona_id)
    assert context["persona_name"] == "Mio"
    assert context["speaking_style"] == "short and gentle"
    assert context["relationship_status"] == "friend"
    assert context["boundaries"] == ["no fake memories"]
    assert context["consent_state"]["save_summary"] is True

    missing = server.video_session_context("default")
    assert missing["persona_id"] == "default"
    assert missing["persona_name"] == ""

    summary = server.video_session_summary(
        {
            "persona_id": str(persona_id),
            "summary_text": "The user tested the video companion bridge.",
            "duration_sec": 125,
            "total_turns": 3,
            "key_topics": ["bridge", "video"],
            "visual_notes": ["user present"],
        }
    )
    assert summary["saved"] is True
    assert summary["conversation_id"] > 0
    assert summary["message_id"] > 0
    assert summary["observation_id"] > 0

    with database.get_db() as db:
        conversation = db.execute(
            "SELECT title, summary FROM conversations WHERE id = ?",
            (summary["conversation_id"],),
        ).fetchone()
        assistant = db.execute(
            "SELECT content FROM messages WHERE id = ?",
            (summary["message_id"],),
        ).fetchone()
        observation = db.execute(
            "SELECT source, observation_type, content FROM world_observations WHERE id = ?",
            (summary["observation_id"],),
        ).fetchone()
    assert conversation["title"] == "视频会话摘要 2分钟"
    assert "video companion bridge" in conversation["summary"]
    assert "video companion bridge" in assistant["content"]
    assert observation["source"] == "video_companion"
    assert observation["observation_type"] == "session_summary"

    obs = server.video_observation(
        {
            "persona_id": str(persona_id),
            "description": "User is visible and smiling.",
            "confidence": 0.9,
            "evidence_type": "video_observation",
        }
    )
    assert obs["saved"] is True
    assert obs["observation"]["confidence"] == 0.9

    consent = server.video_consent(
        {
            "persona_id": str(persona_id),
            "camera": True,
            "microphone": False,
            "external_vision": False,
        }
    )
    assert consent["synced"] is True

    turn = server.video_turn({"persona_id": str(persona_id), "user_text": "hello"})
    assert turn["reply_text"] == ""
    assert turn["persona_found"] is True
    assert turn["memory_policy"]["candidate_only"] is True


def verify_stop_summary_respects_consent(user_id: int, persona_id: int) -> None:
    import app.video_companion as vc

    original_config = vc.load_config
    original_request = vc._request_json
    allow_save = {"value": False}

    def fake_config():
        return {"video_companion": {"enabled": True, "base_url": "http://127.0.0.1:8782"}}

    def fake_request(method, path, payload=None, *, config=None):
        if path != "/api/session/stop":
            return {"ok": True}
        return {
            "status": "stopped",
            "summary": {
                "persona_id": str(persona_id),
                "summary_text": "Video stop summary should follow save consent.",
                "duration_sec": 60,
                "total_turns": 1,
            },
            "consent": {
                "camera": False,
                "microphone": False,
                "external_vision": False,
                "save_summary": allow_save["value"],
                "save_observation": False,
            },
        }

    try:
        vc.load_config = fake_config
        vc._request_json = fake_request

        user = {"id": user_id}
        with database.get_db() as db:
            before_count = int(
                db.execute(
                    "SELECT COUNT(*) AS c FROM conversations WHERE title LIKE '视频会话摘要%'",
                ).fetchone()["c"]
            )

        denied = server.video_companion_stop(user)
        assert denied["mnemosyne_save"]["saved"] is False
        assert denied["mnemosyne_save"]["reason"] == "save_summary_not_granted"

        with database.get_db() as db:
            denied_count = int(
                db.execute(
                    "SELECT COUNT(*) AS c FROM conversations WHERE title LIKE '视频会话摘要%'",
                ).fetchone()["c"]
            )
        assert denied_count == before_count

        allow_save["value"] = True
        allowed = server.video_companion_stop(user)
        assert allowed["mnemosyne_save"]["saved"] is True

        with database.get_db() as db:
            allowed_count = int(
                db.execute(
                    "SELECT COUNT(*) AS c FROM conversations WHERE title LIKE '视频会话摘要%'",
                ).fetchone()["c"]
            )
        assert allowed_count == before_count + 1
    finally:
        vc.load_config = original_config
        vc._request_json = original_request


def verify_video_bridge_auth() -> None:
    from fastapi import HTTPException

    original = os.environ.get("MNEMOSYNE_API_KEY")
    try:
        os.environ.pop("MNEMOSYNE_API_KEY", None)
        assert server._require_video_bridge_auth(None) is None

        os.environ["MNEMOSYNE_API_KEY"] = "secret-token"
        try:
            server._require_video_bridge_auth(None)
            raise AssertionError("bridge auth should require bearer token")
        except HTTPException as exc:
            assert exc.status_code == 401

        try:
            server._require_video_bridge_auth("Bearer wrong")
            raise AssertionError("bridge auth should reject wrong token")
        except HTTPException as exc:
            assert exc.status_code == 403

        assert server._require_video_bridge_auth("Bearer secret-token") is None
    finally:
        if original is None:
            os.environ.pop("MNEMOSYNE_API_KEY", None)
        else:
            os.environ["MNEMOSYNE_API_KEY"] = original


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        database.DB_PATH = Path(tmp) / "video_companion_adapter.db"
        database.init_db()
        user_id = seed_user()
        persona_id = seed_persona(user_id)
        verify_disabled_defaults(user_id)
        verify_env_overrides()
        verify_enabled_adapter_flow(user_id)
        verify_video_bridge_endpoints(user_id, persona_id)
        verify_stop_summary_respects_consent(user_id, persona_id)
        verify_video_bridge_auth()
    print("Video Companion adapter verification passed")


if __name__ == "__main__":
    main()
