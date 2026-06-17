from __future__ import annotations

import asyncio
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
                "INSERT INTO users (username, password_hash, created_at, updated_at) VALUES ('phase5', 'x', ?, ?)",
                (ts, ts),
            ).lastrowid
        )
        db.execute(
            "INSERT INTO user_profiles (user_id, nickname, created_at, updated_at) VALUES (?, 'live2d_test', ?, ?)",
            (user_id, ts, ts),
        )
    return user_id


def verify_live2d_config() -> None:
    import app.live2d as live2d_mod

    assert live2d_mod.live2d_enabled() is False
    config = live2d_mod.load_live2d_config()
    assert config["vts_plugin_name"] == "LINGEmbodiment"
    assert isinstance(config["expression_map"], dict)
    assert "微笑" in config["expression_map"]
    assert config["expression_map"]["微笑"] == "Smile"
    assert "点头" in config["expression_map"]
    assert config["expression_map"]["点头"] == "Nod"
    assert config["idle_expressions"][0] == "Default"
    assert config["listening_expression"] == "Listening"
    assert config["speaking_expression"] == "Talking"
    assert config["thinking_expression"] == "Thinking"


def verify_embodiment() -> None:
    import app.embodiment as emb
    import app.live2d as live2d_mod

    assert emb.expression_to_live2d("微笑") is None

    result = emb.apply_expression_to_live2d("微笑")
    assert result["applied"] is False
    assert result["reason"] == "live2d_disabled"

    runtime_result = emb.apply_runtime_state_to_live2d("speaking")
    assert runtime_result["applied"] is False
    assert runtime_result["reason"] == "live2d_disabled"

    status = emb.live2d_connection_status()
    assert status["enabled"] is False
    assert status["connected"] is False

    original_enabled = emb.live2d_enabled
    original_connection = emb.get_live2d_connection
    try:
        calls: list[str] = []

        class FakeConnection:
            is_connected = True

            def set_expression(self, expression: str) -> bool:
                calls.append(expression)
                return True

        emb.live2d_enabled = lambda: True
        emb.get_live2d_connection = lambda: FakeConnection()
        speaking = emb.apply_runtime_state_to_live2d("speaking")
        listening = emb.apply_runtime_state_to_live2d("listening")
        idle = emb.apply_runtime_state_to_live2d("idle")
        unsupported = emb.apply_runtime_state_to_live2d("dancing")
        assert speaking["applied"] is True
        assert speaking["expression"] == "Talking"
        assert listening["applied"] is True
        assert listening["expression"] == "Listening"
        assert idle["applied"] is True
        assert idle["expression"] == "Default"
        assert unsupported["applied"] is False
        assert unsupported["reason"] == "unsupported_state"
        assert calls == ["Talking", "Listening", "Default"]
    finally:
        emb.live2d_enabled = original_enabled
        emb.get_live2d_connection = original_connection


def verify_expression_mapper() -> None:
    import app.expression_mapper as em

    result = em.map_expression_to_body("微笑")
    assert result is None

    categories = em.get_expression_categories()
    assert categories == {}

    idle = em.get_default_idle_action()
    assert idle == "Default"


def verify_live2d_connection() -> None:
    import app.live2d as live2d_mod

    conn = live2d_mod.Live2DConnection()
    assert conn.is_connected is False
    connected = conn.connect()
    assert connected is False

    expr_result = conn.set_expression("Smile")
    assert expr_result is False

    motion_result = conn.trigger_motion("Nod")
    assert motion_result is False

    status = conn.get_connection_status()
    assert status["enabled"] is False
    assert status["connected"] is False
    assert status["available_hotkey_count"] == 0
    assert status["available_expression_count"] == 0
    assert status["available_model_count"] == 0
    assert status["current_model"] == {}
    assert status["available_models"] == []


def verify_live2d_token_store() -> None:
    import app.live2d as live2d_mod

    original_path = live2d_mod.LIVE2D_TOKEN_PATH
    with tempfile.TemporaryDirectory() as tmp:
        live2d_mod.LIVE2D_TOKEN_PATH = Path(tmp) / "live2d_auth_token.json"
        try:
            conn = live2d_mod.Live2DConnection()
            assert conn._load_auth_token() is None
            conn._save_auth_token("token-123")
            assert conn._load_auth_token() == "token-123"
        finally:
            live2d_mod.LIVE2D_TOKEN_PATH = original_path


def verify_live2d_auth_and_capabilities() -> None:
    import app.live2d as live2d_mod

    async def run() -> None:
        original_path = live2d_mod.LIVE2D_TOKEN_PATH
        with tempfile.TemporaryDirectory() as tmp:
            live2d_mod.LIVE2D_TOKEN_PATH = Path(tmp) / "live2d_auth_token.json"
            try:
                conn = live2d_mod.Live2DConnection()
                requests: list[tuple[str, dict]] = []

                async def fake_send(message_type: str, data: dict | None = None):
                    payload = data or {}
                    requests.append((message_type, payload))
                    if message_type == "AuthenticationTokenRequest":
                        return {"authenticationToken": "token-abc"}
                    if message_type == "AuthenticationRequest":
                        return {"authenticated": payload.get("authenticationToken") == "token-abc"}
                    if message_type == "HotkeysInCurrentModelRequest":
                        return {"availableHotkeys": [{"name": "Nod", "hotkeyID": "hk-nod"}]}
                    if message_type == "ExpressionStateRequest":
                        return {"expressions": [{"file": "Smile.exp3.json", "active": False}]}
                    if message_type == "CurrentModelRequest":
                        return {"modelLoaded": True, "modelName": "Mio Main", "modelID": "model-mio-main"}
                    if message_type == "AvailableModelsRequest":
                        return {
                            "availableModels": [
                                {"modelLoaded": True, "modelName": "Mio Main", "modelID": "model-mio-main"},
                                {"modelName": "Mio Casual", "modelID": "model-mio-casual"},
                            ]
                        }
                    if message_type == "HotkeyTriggerRequest":
                        return {"hotkeyID": payload.get("hotkeyID")}
                    if message_type == "ExpressionActivationRequest":
                        return {}
                    raise AssertionError(f"unexpected VTS request: {message_type}")

                conn._ws = object()
                conn._send_vts_request = fake_send

                assert await conn._authenticate_with_vts("LINGEmbodiment") is True
                assert ("AuthenticationTokenRequest", {
                    "pluginName": "LINGEmbodiment",
                    "pluginDeveloper": "LING",
                }) in requests
                assert conn._load_auth_token() == "token-abc"

                requests.clear()
                assert await conn._authenticate_with_vts("LINGEmbodiment") is True
                assert requests[0][0] == "AuthenticationRequest"
                assert requests[0][1]["authenticationToken"] == "token-abc"

                await conn._refresh_capabilities_async()
                assert conn._find_hotkey_id("Nod") == "hk-nod"
                assert conn._find_hotkey_id("hk-nod") == "hk-nod"
                status = conn.get_connection_status()
                assert status["current_model"]["modelID"] == "model-mio-main"
                assert status["current_model"]["modelName"] == "Mio Main"
                assert status["current_model"]["modelLoaded"] is True
                assert status["available_model_count"] == 2
                assert status["available_models"][1]["modelID"] == "model-mio-casual"

                conn._connected = True
                conn._authenticated = True
                assert await conn.trigger_motion_async("Nod") is True
                assert requests[-1] == ("HotkeyTriggerRequest", {"hotkeyID": "hk-nod"})

                assert await conn.set_expression_async("Smile") is True
                assert requests[-1] == ("ExpressionActivationRequest", {
                    "expressionFile": "Smile.exp3.json",
                    "active": True,
                })

                class FakeClosable:
                    async def close(self):
                        return None

                conn._ws = FakeClosable()
                await conn.disconnect_async()
                status = conn.get_connection_status()
                assert status["connected"] is False
                assert status["authenticated"] is False
                assert status["available_hotkey_count"] == 0
                assert status["available_expression_count"] == 0
                assert status["available_model_count"] == 0
                assert status["current_model"] == {}
                assert status["available_models"] == []
            finally:
                live2d_mod.LIVE2D_TOKEN_PATH = original_path

    asyncio.run(run())


def verify_vts_request_id_filtering() -> None:
    import app.live2d as live2d_mod

    async def run() -> None:
        class FakeWebSocket:
            def __init__(self):
                self.sent: list[str] = []
                self.responses = [
                    {"messageType": "ModelLoadedEvent", "data": {"modelName": "ignored"}},
                    {
                        "apiName": "VTubeStudioPublicAPI",
                        "apiVersion": "1.0",
                        "requestID": "999",
                        "messageType": "HotkeyTriggerRequestResponse",
                        "data": {"ignored": True},
                    },
                    {
                        "apiName": "VTubeStudioPublicAPI",
                        "apiVersion": "1.0",
                        "requestID": "1",
                        "messageType": "HotkeyTriggerRequestResponse",
                        "data": {"ok": True},
                    },
                ]

            async def send(self, payload: str):
                self.sent.append(payload)

            async def recv(self):
                return json_dumps(self.responses.pop(0))

        def json_dumps(value):
            import json
            return json.dumps(value)

        conn = live2d_mod.Live2DConnection()
        ws = FakeWebSocket()
        conn._ws = ws

        result = await conn._send_vts_request("HotkeyTriggerRequest", {"hotkeyID": "hk-nod"})
        assert result == {"ok": True}
        assert len(ws.sent) == 1

    asyncio.run(run())


def verify_server_endpoints(user_id: int) -> None:
    from fastapi import HTTPException

    user = {"id": user_id}

    cfg = server.live2d_config(user)
    assert "live2d" in cfg
    assert cfg["live2d"]["enabled"] is False

    status = server.live2d_status(user)
    assert status["enabled"] is False
    assert status["connected"] is False

    mappings = server.live2d_expression_mappings(user)
    assert mappings["enabled"] is False
    assert mappings["mappings"] == []

    try:
        server.live2d_apply_expression(
            server.Live2DExpressionRequest(label="微笑"),
            user,
        )
        raise AssertionError("should fail when live2d is disabled")
    except HTTPException as exc:
        assert exc.status_code == 400

    try:
        server.live2d_apply_runtime_state(
            server.Live2DRuntimeStateRequest(state="speaking"),
            user,
        )
        raise AssertionError("should fail when live2d is disabled")
    except HTTPException as exc:
        assert exc.status_code == 400

    try:
        server.live2d_connect(user)
        raise AssertionError("should fail when live2d is disabled")
    except HTTPException as exc:
        assert exc.status_code == 400

    try:
        server.live2d_disconnect(user)
        raise AssertionError("should fail when live2d is disabled")
    except HTTPException as exc:
        assert exc.status_code == 400


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        database.DB_PATH = Path(tmp) / "phase5_live2d.db"
        database.init_db()
        user_id = seed_user()
        verify_live2d_config()
        verify_embodiment()
        verify_expression_mapper()
        verify_live2d_connection()
        verify_live2d_token_store()
        verify_live2d_auth_and_capabilities()
        verify_vts_request_id_filtering()
        verify_server_endpoints(user_id)
    print("Phase 5 Live2D embodiment verification passed")


if __name__ == "__main__":
    main()
