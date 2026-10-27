from __future__ import annotations

import json
import socket
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import HTTPException
import requests

from app import acceptance_check, archivist, config, database, environment_check, layered_memory, llm_client, tts_service


def verify_local_voice() -> None:
    voice_config = {"enabled": True, "tts_provider": "local_http", "api_key_env": "OPENAI_API_KEY", "local_base_url": "http://127.0.0.1:9881"}
    healthy = {"ok": True, "service": "ling-local-voice", "model_loaded": True, "configured_voices": 1}

    class Response:
        status = 200
        payload = healthy

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self):
            return json.dumps(self.payload).encode()

    with patch.object(tts_service, "load_voice_config", return_value=voice_config), patch.object(tts_service, "voice_enabled", return_value=True), patch.object(tts_service.urllib.request, "urlopen", return_value=Response()) as request:
        for changes in ({}, {"ok": False}, {"model_loaded": False}, {"service": "other-service"}, {"configured_voices": 0}, {"voice_config_error": "ValueError"}):
            Response.payload = {**healthy, **changes}
            status = tts_service.tts_health_check()
            assert status["available"] is (not bool(changes)), status
            assert status["api_key_env"] == ""
            assert request.call_args.kwargs["timeout"] <= 3
        Response.payload = ["invalid health"]
        assert tts_service.tts_health_check()["available"] is False

    assert "OPENAI_API_KEY" not in environment_check.inspect_environment({"voice": voice_config})["required_env"]
    with patch.object(acceptance_check, "_endpoint_reachable", return_value=False):
        offline = acceptance_check._voice_state({"voice": voice_config}, {"voice_profile": "mio"}, {})
        assert offline["status"] == "pending" and "not reachable" in offline["detail"]
    with patch.object(acceptance_check, "_endpoint_reachable", return_value=True):
        online = acceptance_check._voice_state({"voice": voice_config}, {"voice_profile": "mio"}, {})
        assert online["status"] == "manual"


def verify_voice_settings() -> None:
    with patch.object(server, "_require_self_use_local_config_change"), patch.object(server, "companion_status", return_value={}), patch.object(server, "set_config_section_value") as save:
        result = server.self_use_integration_config(server.SelfUseIntegrationConfigRequest(values={
            "voice.tts_provider": "local_http", "voice.local_base_url": "http://127.0.0.1:9881/", "voice.voice_id": "mio",
        }), None, {})
        assert result["saved"]["voice.local_base_url"] == "http://127.0.0.1:9881"
        assert save.call_count == 3
        for bad_url in ("https://example.com", "http://127.0.0.1:bad", "http://user:password@localhost:9881", "http://localhost:9881?api_key=secret"):
            save.reset_mock()
            try:
                server.self_use_integration_config(server.SelfUseIntegrationConfigRequest(values={
                    "voice.tts_provider": "local_http", "voice.local_base_url": bad_url,
                }), None, {})
            except HTTPException as exc:
                assert exc.status_code == 400
            else:
                raise AssertionError("invalid local voice URL accepted")
            save.assert_not_called()


def verify_safe_errors() -> None:
    for error, expected in (
        (requests.exceptions.ConnectTimeout("secret"), "connection timed out"),
        (requests.exceptions.ReadTimeout("secret"), "response timed out"),
        (requests.exceptions.SSLError("secret"), "TLS"),
        (requests.exceptions.ConnectionError(socket.gaierror("secret")), "DNS"),
        (requests.exceptions.ConnectionError("secret"), "could not connect"),
    ):
        detail = llm_client._probe_request_error(error)
        assert expected in detail and "secret" not in detail, detail
    response = requests.Response()
    response.status_code = 401
    assert "API key" in llm_client._probe_request_error(requests.HTTPError("secret", response=response))
    with tempfile.TemporaryDirectory() as tmp:
        malformed = Path(tmp) / "config.yaml"
        malformed.write_text("llm: [secret-key\n", encoding="utf-8")
        with patch.object(config, "CONFIG_FILE", malformed):
            try:
                config.load_config()
            except ValueError as exc:
                assert "line" in str(exc) and "secret-key" not in str(exc)
            else:
                raise AssertionError("invalid YAML accepted")


def verify_memory_snapshot_refresh() -> None:
    with tempfile.TemporaryDirectory() as tmp, patch.object(database, "DB_PATH", Path(tmp) / "memory.db"), patch.object(archivist, "should_use_llm_for_extraction", return_value=False), patch.object(archivist, "should_use_llm_for_judge", return_value=False):
        database.init_db()
        ts = database.now_ts()
        with database.get_db() as db:
            user_id = db.execute("INSERT INTO users (username, password_hash, created_at, updated_at) VALUES ('snapshot-test', 'x', ?, ?)", (ts, ts)).lastrowid
            persona_id = db.execute("""INSERT INTO personas (user_id, name, summary, prompt, traits_json,
                relationship, speaking_style, boundaries_json, created_at, updated_at)
                VALUES (?, 'test', '', '', '[]', '', '', '[]', ?, ?)""", (user_id, ts, ts)).lastrowid
        def remember(text):
            return archivist.extract_and_store(user_id=user_id, persona_id=persona_id, conversation_id=None, source_message_id=None, user_text=text)
        remember("别叫我宝宝。")
        assert "宝宝" in layered_memory.load_memory_state(user_id, persona_id)["forbidden_addresses"]
        assert "不要称呼用户为：宝宝。" in layered_memory.summary_prompt(user_id, persona_id)
        remember("现在可以叫我宝宝了。")
        assert "宝宝" not in layered_memory.load_memory_state(user_id, persona_id)["forbidden_addresses"]
        assert "不要称呼用户为：宝宝。" not in layered_memory.summary_prompt(user_id, persona_id)
        # A persona-specific refresh must never overwrite a global summary.
        layered_memory._upsert_summary(user_id, None, None, "user_profile", "global evidence", [], "critical", ts)
        remember("我喜欢饭团。")
        assert "饭团" in layered_memory.load_memory_state(user_id, persona_id)["likes"]
        with database.get_db() as db:
            assert db.execute("SELECT text FROM memory_summaries WHERE user_id = ? AND persona_id IS NULL AND archived = 0", (user_id,)).fetchone()[0] == "global evidence"


if __name__ == "__main__":
    # Isolate startup reconciliation before importing the server.
    with tempfile.TemporaryDirectory() as tmp, patch.object(database, "DB_PATH", Path(tmp) / "maintenance.db"):
        from app import server
        verify_local_voice()
        verify_voice_settings()
        verify_safe_errors()
        verify_memory_snapshot_refresh()
    print("Maintenance regressions passed")
