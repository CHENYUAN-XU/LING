from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app.database as database
from app.config import set_config_section_bool, set_config_section_value, set_self_use_chat_enabled


def verify_config_edit() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "config.yaml"
        config_path.write_text(
            "\n".join(
                [
                    "active_persona: \"\"",
                    "",
                    "self_use:",
                    "  enabled: true",
                    "  username: mio_owner",
                    "  # keep manual control",
                    "  chat_enabled: false",
                    "",
                    "llm:",
                    "  provider: ollama",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        set_self_use_chat_enabled(True, config_path)
        enabled_text = config_path.read_text(encoding="utf-8")
        assert "  chat_enabled: true" in enabled_text
        assert "  # keep manual control" in enabled_text
        assert "llm:\n  provider: ollama" in enabled_text

        set_self_use_chat_enabled(False, config_path)
        disabled_text = config_path.read_text(encoding="utf-8")
        assert "  chat_enabled: false" in disabled_text
        assert disabled_text.count("chat_enabled:") == 1

        set_config_section_bool("live2d", "enabled", True, config_path)
        live2d_text = config_path.read_text(encoding="utf-8")
        assert "live2d:\n  enabled: true" in live2d_text
        assert "llm:\n  provider: ollama" in live2d_text

        set_config_section_bool("video_companion", "enabled", False, config_path)
        video_text = config_path.read_text(encoding="utf-8")
        assert "video_companion:\n  enabled: false" in video_text

        set_config_section_value("live2d", "vts_ws_url", "ws://127.0.0.1:9002", config_path)
        url_text = config_path.read_text(encoding="utf-8")
        assert '  vts_ws_url: "ws://127.0.0.1:9002"' in url_text

        set_config_section_value("video_companion", "project_path", r"E:\视觉\video-companion", config_path)
        path_text = config_path.read_text(encoding="utf-8")
        assert '  project_path: "E:\\\\视觉\\\\video-companion"' in path_text


def verify_api_gate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        database.DB_PATH = Path(tmp) / "self_use_chat_gate.db"
        database.init_db()

        import app.auth as auth
        import app.server as server
        from fastapi import HTTPException

        backing_config = {
            "self_use": {
                "enabled": True,
                "chat_enabled": False,
                "require_localhost": True,
                "username": "mio_owner",
            }
        }
        missing_llm = {
            "task": "chat",
            "provider": "kimi",
            "model": "moonshot-v1-auto",
            "api_key_env": "MOONSHOT_API_KEY",
            "requires_api_key": True,
            "configured": False,
            "verified": False,
            "verification": {"state": "unverified", "checked_at": None},
            "missing": ["MOONSHOT_API_KEY"],
        }
        ready_llm = {
            "task": "chat",
            "provider": "ollama",
            "model": "qwen2.5:3b",
            "api_key_env": "",
            "requires_api_key": False,
            "configured": True,
            "verified": True,
            "verification": {"state": "verified", "checked_at": 123},
            "missing": [],
        }
        llm_state = {"value": missing_llm}

        original_load_config = server.load_config
        original_llm_runtime_status = server.llm_runtime_status
        original_set_self_use_chat_enabled = server.set_self_use_chat_enabled
        original_set_config_section_bool = server.set_config_section_bool
        original_set_config_section_value = server.set_config_section_value
        original_companion_status = server.companion_status
        original_probe_llm_runtime = server.probe_llm_runtime
        original_require_bound_persona = server._require_self_use_bound_persona
        original_start_live2d_autoconnect = server.start_live2d_autoconnect
        original_stop_live2d_connection = server.stop_live2d_connection
        try:
            server.load_config = lambda: backing_config
            server.llm_runtime_status = lambda task="chat": dict(llm_state["value"], task=task)
            server.set_self_use_chat_enabled = lambda enabled: backing_config["self_use"].__setitem__(
                "chat_enabled",
                bool(enabled),
            )
            integration_flags: list[tuple[str, str, bool]] = []
            server.set_config_section_bool = lambda section, key, enabled: integration_flags.append(
                (section, key, bool(enabled))
            )
            integration_values: list[tuple[str, str, str]] = []
            server.set_config_section_value = lambda section, key, value: integration_values.append(
                (section, key, str(value))
            )
            server.companion_status = lambda user: {"self_use": backing_config["self_use"], "ok": True}
            server.probe_llm_runtime = lambda task="chat": {
                "ok": True,
                "state": "verified",
                "provider": "ollama",
                "model": "qwen2.5:3b",
            }
            server._require_self_use_bound_persona = lambda _user, _persona_id: None
            live2d_lifecycle: list[str] = []
            server.start_live2d_autoconnect = lambda **_kwargs: live2d_lifecycle.append("start") or {"started": True}
            server.stop_live2d_connection = lambda: live2d_lifecycle.append("stop") or {"connected": False}

            user = auth.get_or_create_local_user("mio_owner", "Mio")
            local_request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
            remote_request = SimpleNamespace(client=SimpleNamespace(host="192.168.1.12"))

            try:
                server.self_use_chat_gate(server.SelfUseChatGateRequest(enabled=True), local_request, user)
                raise AssertionError("missing API key should keep the chat gate closed")
            except HTTPException as exc:
                assert exc.status_code == 400
                assert exc.detail["reason"] == "missing_api_key"
                assert exc.detail["missing"] == ["MOONSHOT_API_KEY"]

            try:
                server.self_use_chat_gate(server.SelfUseChatGateRequest(enabled=False), remote_request, user)
                raise AssertionError("remote requests should not change the local chat gate")
            except HTTPException as exc:
                assert exc.status_code == 403

            probe = server.self_use_llm_probe(local_request, user)
            assert probe["probe"]["ok"] is True
            try:
                server.self_use_llm_probe(remote_request, user)
                raise AssertionError("remote requests should not probe the local model route")
            except HTTPException as exc:
                assert exc.status_code == 403

            from fastapi import BackgroundTasks

            backing_config["self_use"]["chat_enabled"] = True
            llm_state["value"] = {
                **ready_llm,
                "verified": False,
                "verification": {"state": "unverified", "checked_at": None},
            }
            try:
                server.chat(
                    server.ChatRequest(message="hello", persona_id=1),
                    BackgroundTasks(),
                    user,
                )
                raise AssertionError("self-use chat must reject an unverified model route")
            except HTTPException as exc:
                assert exc.status_code == 503
                assert exc.detail["reason"] == "llm_unverified"
            backing_config["self_use"]["chat_enabled"] = False

            llm_state["value"] = ready_llm
            enabled = server.self_use_chat_gate(server.SelfUseChatGateRequest(enabled=True), local_request, user)
            assert enabled["self_use"]["chat_enabled"] is True
            assert enabled["chat_gate"]["ready"] is True
            assert enabled["chat_gate"]["reason"] == "ready"

            disabled = server.self_use_chat_gate(server.SelfUseChatGateRequest(enabled=False), local_request, user)
            assert disabled["self_use"]["chat_enabled"] is False
            assert disabled["chat_gate"]["enabled"] is False
            assert disabled["chat_gate"]["can_enable"] is True

            live2d = server.self_use_integration_flag(
                server.SelfUseIntegrationFlagRequest(key="live2d", enabled=True),
                local_request,
                user,
            )
            assert live2d["key"] == "live2d"
            assert live2d["enabled"] is True
            assert integration_flags[-1] == ("live2d", "enabled", True)
            assert live2d_lifecycle == ["start"]

            live2d_off = server.self_use_integration_flag(
                server.SelfUseIntegrationFlagRequest(key="live2d", enabled=False),
                local_request,
                user,
            )
            assert live2d_off["enabled"] is False
            assert integration_flags[-1] == ("live2d", "enabled", False)
            assert live2d_lifecycle == ["start", "stop"]

            video = server.self_use_integration_flag(
                server.SelfUseIntegrationFlagRequest(key="video_companion", enabled=False),
                local_request,
                user,
            )
            assert video["key"] == "video_companion"
            assert integration_flags[-1] == ("video_companion", "enabled", False)

            voice = server.self_use_integration_flag(
                server.SelfUseIntegrationFlagRequest(key="voice", enabled=True),
                local_request,
                user,
            )
            assert voice["key"] == "voice"
            assert voice["enabled"] is True
            assert integration_flags[-1] == ("voice", "enabled", True)

            screen = server.self_use_integration_flag(
                server.SelfUseIntegrationFlagRequest(key="screen", enabled=True),
                local_request,
                user,
            )
            assert screen["key"] == "screen"
            assert integration_flags[-1] == ("screen", "enabled", True)

            proactive = server.self_use_integration_flag(
                server.SelfUseIntegrationFlagRequest(key="proactive", enabled=True),
                local_request,
                user,
            )
            assert proactive["key"] == "proactive"
            assert integration_flags[-1] == ("proactive", "enabled", True)

            try:
                server.self_use_integration_flag(
                    server.SelfUseIntegrationFlagRequest(key="camera", enabled=True),
                    local_request,
                    user,
                )
                raise AssertionError("unsupported integration flags should be rejected")
            except HTTPException as exc:
                assert exc.status_code == 400

            config_update = server.self_use_integration_config(
                server.SelfUseIntegrationConfigRequest(values={
                    "live2d.vts_ws_url": "ws://127.0.0.1:9002",
                    "live2d.idle_expression": "Idle",
                    "live2d.listening_expression": "Listen",
                    "live2d.thinking_expression": "Think",
                    "live2d.speaking_expression": "Talk",
                    "live2d.lip_sync_enabled": "true",
                    "live2d.lip_sync_parameter": "MouthOpen",
                    "live2d.lip_sync_gain": "2.5",
                    "voice.tts_provider": "openai_tts",
                    "voice.tts_model": "gpt-4o-mini-tts",
                    "voice.api_key_env": "OPENAI_API_KEY",
                    "voice.voice_id": "marin",
                    "voice.response_format": "mp3",
                    "voice.rate": "1.15",
                    "voice.max_chunk_length": "120",
                    "voice.instructions": "Speak naturally.",
                    "voice.auto_play": "false",
                    "video_companion.base_url": "http://127.0.0.1:8782/",
                    "video_companion.ws_url": "ws://127.0.0.1:8782/ws",
                    "video_companion.project_path": r"E:\视觉\video-companion",
                }),
                local_request,
                user,
            )
            assert config_update["saved"]["live2d.vts_ws_url"] == "ws://127.0.0.1:9002"
            assert config_update["saved"]["live2d.idle_expression"] == "Idle"
            assert config_update["saved"]["live2d.listening_expression"] == "Listen"
            assert config_update["saved"]["live2d.thinking_expression"] == "Think"
            assert config_update["saved"]["live2d.speaking_expression"] == "Talk"
            assert config_update["saved"]["live2d.lip_sync_enabled"] is True
            assert config_update["saved"]["live2d.lip_sync_parameter"] == "MouthOpen"
            assert config_update["saved"]["live2d.lip_sync_gain"] == "2.5"
            assert config_update["saved"]["voice.tts_provider"] == "openai_tts"
            assert config_update["saved"]["voice.tts_model"] == "gpt-4o-mini-tts"
            assert config_update["saved"]["voice.api_key_env"] == "OPENAI_API_KEY"
            assert config_update["saved"]["voice.voice_id"] == "marin"
            assert config_update["saved"]["voice.response_format"] == "mp3"
            assert config_update["saved"]["voice.rate"] == "1.15"
            assert config_update["saved"]["voice.max_chunk_length"] == "120"
            assert config_update["saved"]["voice.instructions"] == "Speak naturally."
            assert config_update["saved"]["voice.auto_play"] is False
            assert config_update["saved"]["video_companion.base_url"] == "http://127.0.0.1:8782"
            assert ("live2d", "vts_ws_url", "ws://127.0.0.1:9002") in integration_values
            assert ("live2d", "idle_expression", "Idle") in integration_values
            assert ("live2d", "listening_expression", "Listen") in integration_values
            assert ("live2d", "thinking_expression", "Think") in integration_values
            assert ("live2d", "speaking_expression", "Talk") in integration_values
            assert ("live2d", "lip_sync_enabled", "True") in integration_values
            assert ("live2d", "lip_sync_parameter", "MouthOpen") in integration_values
            assert ("live2d", "lip_sync_gain", "2.5") in integration_values
            assert ("voice", "tts_provider", "openai_tts") in integration_values
            assert ("voice", "api_key_env", "OPENAI_API_KEY") in integration_values
            assert ("voice", "voice_id", "marin") in integration_values
            assert ("voice", "auto_play", "False") in integration_values
            assert ("video_companion", "project_path", r"E:\视觉\video-companion") in integration_values

            try:
                server.self_use_integration_config(
                    server.SelfUseIntegrationConfigRequest(values={"live2d.vts_ws_url": "http://127.0.0.1:9002"}),
                    local_request,
                    user,
                )
                raise AssertionError("invalid websocket URLs should be rejected")
            except HTTPException as exc:
                assert exc.status_code == 400

            try:
                server.self_use_integration_config(
                    server.SelfUseIntegrationConfigRequest(values={"live2d.speaking_expression": "Talk\nNow"}),
                    local_request,
                    user,
                )
                raise AssertionError("multi-line Live2D action names should be rejected")
            except HTTPException as exc:
                assert exc.status_code == 400

            try:
                server.self_use_integration_config(
                    server.SelfUseIntegrationConfigRequest(values={"live2d.lip_sync_gain": "20"}),
                    local_request,
                    user,
                )
                raise AssertionError("out-of-range lip sync gain should be rejected")
            except HTTPException as exc:
                assert exc.status_code == 400

            try:
                server.self_use_integration_config(
                    server.SelfUseIntegrationConfigRequest(values={"voice.tts_provider": "edge"}),
                    local_request,
                    user,
                )
                raise AssertionError("edge TTS should stay unavailable for LING")
            except HTTPException as exc:
                assert exc.status_code == 400

            try:
                server.self_use_integration_config(
                    server.SelfUseIntegrationConfigRequest(values={"voice.tts_provider": "elevenlabs"}),
                    local_request,
                    user,
                )
                raise AssertionError("unimplemented TTS providers must not be configurable")
            except HTTPException as exc:
                assert exc.status_code == 400
                assert "must be openai_tts" in str(exc.detail)

            try:
                server.self_use_integration_config(
                    server.SelfUseIntegrationConfigRequest(values={"voice.api_key_env": "OPENAI-KEY"}),
                    local_request,
                    user,
                )
                raise AssertionError("invalid env names should be rejected")
            except HTTPException as exc:
                assert exc.status_code == 400

            try:
                server.self_use_integration_config(
                    server.SelfUseIntegrationConfigRequest(values={"voice.auto_play": "sometimes"}),
                    local_request,
                    user,
                )
                raise AssertionError("invalid voice auto-play values should be rejected")
            except HTTPException as exc:
                assert exc.status_code == 400

            try:
                server.self_use_integration_config(
                    server.SelfUseIntegrationConfigRequest(values={"voice.rate": "9"}),
                    local_request,
                    user,
                )
                raise AssertionError("out-of-range voice rates should be rejected")
            except HTTPException as exc:
                assert exc.status_code == 400

            try:
                server.self_use_integration_config(
                    server.SelfUseIntegrationConfigRequest(values={"voice.response_format": "wav"}),
                    local_request,
                    user,
                )
                raise AssertionError("multi-chunk reply playback must stay on mp3")
            except HTTPException as exc:
                assert exc.status_code == 400
                assert "must be mp3" in str(exc.detail)

            try:
                server.self_use_integration_config(
                    server.SelfUseIntegrationConfigRequest(values={"llm.api_key": "secret"}),
                    local_request,
                    user,
                )
                raise AssertionError("unsupported config keys should be rejected")
            except HTTPException as exc:
                assert exc.status_code == 400

            assert server.group_conversations(user)["group_conversations"] == []
            for call in (
                lambda: server.create_group_conversation_endpoint(
                    server.GroupConversationCreateRequest(title="legacy", persona_ids=[1, 2]),
                    user,
                ),
                lambda: server.group_conversation_messages(1, user),
                lambda: server.mark_group_read(1, user),
                lambda: server.patch_group_conversation(
                    1,
                    server.GroupConversationUpdateRequest(title="legacy"),
                    user,
                ),
                lambda: server.group_chat_endpoint(
                    server.GroupChatRequest(group_conversation_id=1, message="legacy"),
                    user,
                ),
            ):
                try:
                    call()
                    raise AssertionError("self-use mode should block group conversation endpoints")
                except HTTPException as exc:
                    assert exc.status_code == 403
        finally:
            server.load_config = original_load_config
            server.llm_runtime_status = original_llm_runtime_status
            server.set_self_use_chat_enabled = original_set_self_use_chat_enabled
            server.set_config_section_bool = original_set_config_section_bool
            server.set_config_section_value = original_set_config_section_value
            server.companion_status = original_companion_status
            server.probe_llm_runtime = original_probe_llm_runtime
            server._require_self_use_bound_persona = original_require_bound_persona
            server.start_live2d_autoconnect = original_start_live2d_autoconnect
            server.stop_live2d_connection = original_stop_live2d_connection


def main() -> None:
    verify_config_edit()
    verify_api_gate()
    print("Self-use chat gate verification passed")


if __name__ == "__main__":
    main()
