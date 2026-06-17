from __future__ import annotations

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
                "INSERT INTO users (username, password_hash, created_at, updated_at) VALUES ('phase4', 'x', ?, ?)",
                (ts, ts),
            ).lastrowid
        )
        db.execute(
            "INSERT INTO user_profiles (user_id, nickname, created_at, updated_at) VALUES (?, 'voice_test', ?, ?)",
            (user_id, ts, ts),
        )
    return user_id


def verify_voice_config() -> None:
    import app.voice as voice_mod

    assert voice_mod.voice_enabled() is False
    config = voice_mod.load_voice_config()
    assert config["tts_provider"] == "openai_tts"
    assert config["voice_id"] == "alloy"
    assert config["split_long_replies"] is True
    assert config["max_chunk_length"] == 80
    assert isinstance(config["expression_style_map"], dict)
    assert config["expression_style_map"]["微笑"] == "cheerful"
    assert config["expression_style_map"]["轻笑"] == "cheerful"
    assert config["expression_style_map"]["担心"] == "concerned"
    assert config["expression_style_map"]["轻声"] == "gentle"
    assert config["expression_style_map"]["停顿"] == "default"
    assert config["expression_style_map"]["点头"] == "default"


def verify_speech_planner() -> None:
    import app.speech_planner as sp

    short = sp.split_reply_into_utterances("我在。")
    assert short == ["我在。"]

    multi = sp.split_reply_into_utterances("先坐一会儿。今天过得怎么样？")
    assert len(multi) >= 2
    assert multi[0] == "先坐一会儿。"

    long_text = "这是一句比较长的回复内容，包含了许多文字用来测试分段功能是否正常工作。"
    segments = sp.split_reply_into_utterances(long_text)
    assert len(segments) == 1
    assert segments[0] == long_text

    params = sp.build_tts_request_params(["你好"], ["微笑"])
    assert len(params) == 1
    assert params[0]["text"] == "你好"
    assert params[0]["voice_id"] == "alloy"
    assert params[0]["style"] == "cheerful"

    params_no_style = sp.build_tts_request_params(["你好"], ["未知标签"])
    assert params_no_style[0].get("style") is None or params_no_style[0].get("style") == "default"

    params_no_label = sp.build_tts_request_params(["你好"])
    assert len(params_no_label) == 1


def verify_tts_service_disabled() -> None:
    import app.tts_service as tts_svc

    health = tts_svc.tts_health_check()
    assert health["enabled"] is False
    assert health["available"] is False

    result = tts_svc.generate_tts_audio("测试")
    assert result is None
    assert tts_svc.get_last_tts_error() == "voice is disabled"


def verify_tts_failure_metadata_and_cleanup() -> None:
    import app.tts_service as tts_svc

    original_enabled = tts_svc.voice_enabled
    original_config = tts_svc.load_voice_config
    try:
        tts_svc.voice_enabled = lambda: True
        tts_svc.load_voice_config = lambda: {
            "enabled": True,
            "tts_provider": "openai_tts",
            "voice_id": "alloy",
            "rate": 1.0,
            "pitch": 1.0,
        }
        audio = tts_svc.generate_tts_audio("测试")
        assert audio is None
        assert "Video Companion" in (tts_svc.get_last_tts_error() or "")
    finally:
        tts_svc.voice_enabled = original_enabled
        tts_svc.load_voice_config = original_config

    original_enabled = tts_svc.voice_enabled
    original_config = tts_svc.load_voice_config
    try:
        tts_svc.voice_enabled = lambda: True
        tts_svc.load_voice_config = lambda: {
            "enabled": True,
            "tts_provider": "edge",
            "voice_id": "zh-CN-XiaoxiaoNeural",
            "rate": 1.0,
            "pitch": 1.0,
        }
        audio = tts_svc.generate_tts_audio("测试")
        assert audio is None
        assert "edge TTS is disabled" in (tts_svc.get_last_tts_error() or "")
        health = tts_svc.tts_health_check()
        assert health["available"] is False
        assert "edge TTS is disabled" in (health["error"] or "")
    finally:
        tts_svc.voice_enabled = original_enabled
        tts_svc.load_voice_config = original_config

    original_enabled = tts_svc.voice_enabled
    original_generate = tts_svc.generate_tts_audio
    try:
        tts_svc.voice_enabled = lambda: True

        def fake_generate(*args, **kwargs):
            tts_svc._set_tts_error("network unavailable")
            return None

        tts_svc.generate_tts_audio = fake_generate
        result = tts_svc.generate_tts_reply_audio("你好。")
        assert result["success"] is False
        assert result["chunks"][0]["error"] == "network unavailable"

        audio, metadata = tts_svc.generate_tts_single_chunk("你好。", 0)
        assert audio is None
        assert metadata["error"] == "network unavailable"
    finally:
        tts_svc.voice_enabled = original_enabled
        tts_svc.generate_tts_audio = original_generate


def verify_server_endpoints(user_id: int) -> None:
    user = {"id": user_id}

    voice_cfg = server.voice_config(user)
    assert "voice" in voice_cfg
    assert voice_cfg["voice"]["enabled"] is False

    health = server.voice_health(user)
    assert health["enabled"] is False

    from fastapi import HTTPException

    try:
        server.voice_tts(server.VoiceTTSRequest(text="测试"), user)
        raise AssertionError("should fail when voice is disabled")
    except HTTPException as exc:
        assert exc.status_code == 400

    try:
        server.voice_tts(server.VoiceTTSRequest(text="   "), user)
        raise AssertionError("blank voice text should be rejected as a bad request")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "不能为空" in str(exc.detail)

    try:
        server.voice_tts_reply(server.VoiceTTSReplyRequest(reply_text="测试回复。"), user)
        raise AssertionError("should fail when voice is disabled")
    except HTTPException as exc:
        assert exc.status_code == 400

    try:
        server.voice_speech_plan(server.VoiceTTSReplyRequest(reply_text="   "), user)
        raise AssertionError("blank speech plan text should be rejected")
    except HTTPException as exc:
        assert exc.status_code == 400

    plan = server.voice_speech_plan(server.VoiceTTSReplyRequest(reply_text="你好。今天怎么样？"), user)
    assert len(plan["utterances"]) >= 2
    assert len(plan["tts_params"]) == len(plan["utterances"])
    assert plan["chunk_count"] == len(plan["utterances"])
    assert plan["styles"] == []
    assert plan["expression_labels"] == []

    styled_plan = server.voice_speech_plan(
        server.VoiceTTSReplyRequest(reply_text="你好。", expression_labels=["微笑"]),
        user,
    )
    assert styled_plan["chunk_count"] == 1
    assert styled_plan["styles"] == ["cheerful"]
    assert styled_plan["expression_labels"] == ["微笑"]


def verify_server_voice_error_detail(user_id: int) -> None:
    from fastapi import HTTPException

    user = {"id": user_id}
    original_enabled = server.voice_enabled
    original_generate = server.generate_tts_audio
    original_last_error = server.get_last_tts_error
    try:
        server.voice_enabled = lambda: True
        server.generate_tts_audio = lambda **kwargs: None
        server.get_last_tts_error = lambda: "network unavailable"
        try:
            server.voice_tts(server.VoiceTTSRequest(text="测试"), user)
            raise AssertionError("should fail when TTS generation fails")
        except HTTPException as exc:
            assert exc.status_code == 503
            assert "network unavailable" in str(exc.detail)
    finally:
        server.voice_enabled = original_enabled
        server.generate_tts_audio = original_generate
        server.get_last_tts_error = original_last_error


def verify_server_voice_chunk_bad_request(user_id: int) -> None:
    from fastapi import HTTPException

    user = {"id": user_id}
    original_enabled = server.voice_enabled
    original_chunk = server.generate_tts_single_chunk
    try:
        server.voice_enabled = lambda: True
        server.generate_tts_single_chunk = lambda reply_text, chunk_index, expression_labels=None: (
            None,
            {"error": f"chunk_index {chunk_index} out of range (0-0)"},
        )
        try:
            server.voice_tts_chunk(9, server.VoiceTTSReplyRequest(reply_text="你好。"), user)
            raise AssertionError("out-of-range TTS chunk should be a bad request")
        except HTTPException as exc:
            assert exc.status_code == 400
            assert "chunk_index" in str(exc.detail)
    finally:
        server.voice_enabled = original_enabled
        server.generate_tts_single_chunk = original_chunk


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        database.DB_PATH = Path(tmp) / "phase4_voice.db"
        database.init_db()
        user_id = seed_user()
        verify_voice_config()
        verify_speech_planner()
        verify_tts_service_disabled()
        verify_tts_failure_metadata_and_cleanup()
        verify_server_endpoints(user_id)
        verify_server_voice_error_detail(user_id)
        verify_server_voice_chunk_bad_request(user_id)
    print("Phase 4 TTS voice personality verification passed")


if __name__ == "__main__":
    main()
