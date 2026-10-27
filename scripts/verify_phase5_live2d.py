from __future__ import annotations

import asyncio
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch


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
    assert config["lip_sync_enabled"] is True
    assert config["lip_sync_parameter"] == "MouthOpen"
    assert config["lip_sync_gain"] == 2.2

    original_load_config = live2d_mod.load_config
    try:
        live2d_mod.load_config = lambda: {"live2d": {"idle_expression": "IdleCustom"}}
        custom_config = live2d_mod.load_live2d_config()
        assert custom_config["idle_expressions"][0] == "IdleCustom"
    finally:
        live2d_mod.load_config = original_load_config


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
    assert status["connecting"] is False
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
    assert status["available_parameter_count"] == 0
    assert status["available_parameters"] == []
    assert status["capabilities_stale"] is True
    assert status["capabilities_updated_at"] == 0


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
                    if message_type == "InputParameterListRequest":
                        return {
                            "defaultParameters": [
                                {"name": "MouthOpen", "addedBy": "VTube Studio", "min": 0, "max": 1}
                            ],
                            "customParameters": [],
                        }
                    if message_type == "HotkeyTriggerRequest":
                        return {"hotkeyID": payload.get("hotkeyID")}
                    if message_type == "ExpressionActivationRequest":
                        return {}
                    if message_type == "InjectParameterDataRequest":
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
                assert status["available_hotkeys"] == [{"name": "Nod", "hotkeyID": "hk-nod"}]
                assert status["available_expressions"] == [{"file": "Smile.exp3.json", "active": False}]
                assert status["available_parameter_count"] == 1
                assert status["available_parameters"][0]["name"] == "MouthOpen"
                assert status["capabilities_stale"] is False
                assert status["capabilities_updated_at"] > 0

                conn._connected = True
                conn._authenticated = True
                requests.clear()
                assert await conn.refresh_capabilities_async() is True
                assert [item[0] for item in requests] == [
                    "CurrentModelRequest",
                    "HotkeysInCurrentModelRequest",
                    "ExpressionStateRequest",
                    "AvailableModelsRequest",
                    "InputParameterListRequest",
                ]

                previous_status = conn.get_connection_status()

                async def partial_refresh(message_type: str, data: dict | None = None):
                    if message_type == "CurrentModelRequest":
                        return {"modelLoaded": True, "modelName": "Mio New", "modelID": "model-mio-new"}
                    if message_type == "HotkeysInCurrentModelRequest":
                        return False
                    raise AssertionError(f"partial refresh should stop after hotkey failure: {message_type}")

                conn._send_vts_request = partial_refresh
                assert await conn.refresh_capabilities_async() is False
                stale_status = conn.get_connection_status()
                assert stale_status["capabilities_stale"] is True
                assert stale_status["current_model"] == previous_status["current_model"]
                assert stale_status["available_hotkeys"] == previous_status["available_hotkeys"]
                conn._send_vts_request = fake_send
                assert await conn.refresh_capabilities_async() is True

                requests.clear()
                assert await conn.inject_parameter_async("MouthOpen", 0.65) is True
                assert requests[-1] == ("InjectParameterDataRequest", {
                    "faceFound": False,
                    "mode": "set",
                    "parameterValues": [{"id": "MouthOpen", "value": 0.65, "weight": 1.0}],
                })
                assert await conn.inject_parameter_async("MissingParameter", 0.5) is False

                assert await conn.trigger_motion_async("Nod") is True
                assert requests[-1] == ("HotkeyTriggerRequest", {"hotkeyID": "hk-nod"})

                assert await conn.set_expression_async("Smile") is True
                assert requests[-1] == ("ExpressionActivationRequest", {
                    "expressionFile": "Smile.exp3.json",
                    "active": True,
                })
                assert await conn.set_expression_async("Default") is True
                assert requests[-1] == ("ExpressionActivationRequest", {
                    "expressionFile": "Smile.exp3.json",
                    "active": False,
                })
                assert await conn.set_expression_async("Nod") is True
                assert requests[-1] == ("HotkeyTriggerRequest", {"hotkeyID": "hk-nod"})

                # VTS can expose a model with hotkeys but no expression-state
                # entries. The action must still use the real hotkey instead
                # of a fabricated Nod.exp3.json path.
                conn._available_expressions = []
                assert conn._find_expression_file("Nod") is None
                assert await conn.set_expression_async("Nod") is True
                assert requests[-1] == ("HotkeyTriggerRequest", {"hotkeyID": "hk-nod"})
                assert conn._find_expression_file("Manual.exp3.json") == "Manual.exp3.json"

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
                assert status["available_parameters"] == []
                assert status["capabilities_stale"] is True
                assert status["capabilities_updated_at"] == 0
            finally:
                live2d_mod.LIVE2D_TOKEN_PATH = original_path

    asyncio.run(run())


def verify_sync_connection_loop_lifetime() -> None:
    import app.live2d as live2d_mod

    conn = live2d_mod.Live2DConnection()
    original_enabled = live2d_mod.live2d_enabled
    loop_ids: list[int] = []

    async def fake_connect() -> bool:
        conn._connection_loop = asyncio.get_running_loop()
        conn._connected = True
        conn._authenticated = True
        loop_ids.append(id(asyncio.get_running_loop()))
        return True

    async def fake_expression(_name: str) -> bool:
        loop_ids.append(id(asyncio.get_running_loop()))
        return True

    async def fake_refresh() -> bool:
        loop_ids.append(id(asyncio.get_running_loop()))
        return True

    async def fake_disconnect() -> None:
        loop_ids.append(id(asyncio.get_running_loop()))
        conn._connected = False
        conn._authenticated = False
        conn._connection_loop = None

    try:
        live2d_mod.live2d_enabled = lambda: True
        conn.connect_async = fake_connect
        conn.set_expression_async = fake_expression
        conn.refresh_capabilities_async = fake_refresh
        conn.disconnect_async = fake_disconnect
        assert conn.connect() is True
        assert conn.set_expression("Smile") is True
        assert conn.refresh_capabilities() is True
        assert conn._background_thread is not None and conn._background_thread.is_alive()
        conn.disconnect()
        assert conn.is_connected is False
        assert len(set(loop_ids)) == 1
        assert conn._background_thread is None
        assert conn._background_loop is None
    finally:
        live2d_mod.live2d_enabled = original_enabled
        conn.disconnect()


def verify_live2d_autoconnect_lifecycle() -> None:
    import app.embodiment as emb

    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    class FakeConnection:
        is_connected = False
        is_connecting = False

        def connect(self) -> bool:
            self.is_connecting = True
            calls.append("connect")
            entered.set()
            release.wait(timeout=2)
            self.is_connecting = False
            self.is_connected = True
            return True

        def disconnect(self) -> None:
            calls.append("disconnect")
            self.is_connected = False

        def get_connection_status(self) -> dict:
            return {"connected": self.is_connected, "connecting": self.is_connecting}

    fake = FakeConnection()
    original_enabled = emb.live2d_enabled
    original_connection = emb.get_live2d_connection
    original_thread = emb._live2d_autoconnect_thread
    original_paused = emb._live2d_autoconnect_paused
    original_delays = emb.LIVE2D_RECONNECT_DELAYS
    try:
        emb.live2d_enabled = lambda: True
        emb.get_live2d_connection = lambda: fake
        emb._live2d_autoconnect_thread = None
        emb._live2d_autoconnect_paused = False
        emb.LIVE2D_RECONNECT_DELAYS = (0.0,)
        started = emb.start_live2d_autoconnect()
        assert started == {"started": True, "reason": "startup_autoconnect"}
        assert entered.wait(timeout=1)
        duplicate = emb.start_live2d_autoconnect()
        assert duplicate == {"started": False, "reason": "already_connecting"}
        release.set()
        thread = emb._live2d_autoconnect_thread
        assert thread is not None
        thread.join(timeout=2)
        assert fake.is_connected is True
        stopped = emb.stop_live2d_connection()
        assert stopped["connected"] is False
        assert calls == ["connect", "disconnect"]
        paused = emb.start_live2d_autoconnect()
        assert paused == {"started": False, "reason": "manually_paused"}
    finally:
        release.set()
        emb.live2d_enabled = original_enabled
        emb.get_live2d_connection = original_connection
        emb._live2d_autoconnect_thread = original_thread
        emb._live2d_autoconnect_paused = original_paused
        emb.LIVE2D_RECONNECT_DELAYS = original_delays


def verify_live2d_autoconnect_retries() -> None:
    import app.embodiment as emb

    class RetryConnection:
        is_connected = False
        is_connecting = False
        attempts = 0

        def connect(self) -> bool:
            self.attempts += 1
            self.is_connected = self.attempts >= 3
            return self.is_connected

    fake = RetryConnection()
    original_enabled = emb.live2d_enabled
    original_connection = emb.get_live2d_connection
    original_thread = emb._live2d_autoconnect_thread
    original_paused = emb._live2d_autoconnect_paused
    original_delays = emb.LIVE2D_RECONNECT_DELAYS
    try:
        emb.live2d_enabled = lambda: True
        emb.get_live2d_connection = lambda: fake
        emb._live2d_autoconnect_thread = None
        emb._live2d_autoconnect_paused = False
        emb.LIVE2D_RECONNECT_DELAYS = (0.0, 0.0, 0.0, 0.0)
        started = emb.start_live2d_autoconnect(force=True)
        assert started["started"] is True
        thread = emb._live2d_autoconnect_thread
        assert thread is not None
        thread.join(timeout=2)
        assert fake.attempts == 3
        assert fake.is_connected is True
    finally:
        emb._live2d_autoconnect_stop.set()
        emb.live2d_enabled = original_enabled
        emb.get_live2d_connection = original_connection
        emb._live2d_autoconnect_thread = original_thread
        emb._live2d_autoconnect_paused = original_paused
        emb.LIVE2D_RECONNECT_DELAYS = original_delays


def verify_vts_request_serialization() -> None:
    import app.live2d as live2d_mod

    async def run() -> None:
        class FakeWebSocket:
            def __init__(self):
                self.sent: list[dict] = []
                self.active_receivers = 0
                self.max_active_receivers = 0

            async def send(self, payload: str):
                import json
                self.sent.append(json.loads(payload))

            async def recv(self):
                import json
                self.active_receivers += 1
                self.max_active_receivers = max(self.max_active_receivers, self.active_receivers)
                try:
                    await asyncio.sleep(0.01)
                    request = self.sent[-1]
                    return json.dumps({
                        "requestID": request["requestID"],
                        "messageType": f'{request["messageType"]}Response',
                        "data": {"ok": True},
                    })
                finally:
                    self.active_receivers -= 1

        conn = live2d_mod.Live2DConnection()
        ws = FakeWebSocket()
        conn._ws = ws
        first, second = await asyncio.gather(
            conn._send_vts_request("CurrentModelRequest"),
            conn._send_vts_request("AvailableModelsRequest"),
        )
        assert first == {"ok": True}
        assert second == {"ok": True}
        assert ws.max_active_receivers == 1

    asyncio.run(run())


def verify_vts_timeout_disconnects() -> None:
    import app.live2d as live2d_mod

    async def run() -> None:
        class TimeoutWebSocket:
            closed = False

            async def send(self, _payload: str):
                return None

            async def recv(self):
                raise asyncio.TimeoutError

            async def close(self):
                self.closed = True

        conn = live2d_mod.Live2DConnection()
        ws = TimeoutWebSocket()
        conn._ws = ws
        conn._connected = True
        conn._authenticated = True
        conn._available_hotkeys = [{"name": "Nod", "hotkeyID": "hk-nod"}]
        conn._capabilities_stale = False
        result = await conn._send_vts_request("CurrentModelRequest")
        assert result is False
        assert ws.closed is True
        status = conn.get_connection_status()
        assert status["connected"] is False
        assert status["authenticated"] is False
        assert status["capabilities_stale"] is True
        assert status["available_hotkeys"] == []
        assert status["last_error"] == "VTS request timed out"

    asyncio.run(run())


def verify_background_schedule_failure_closes_coroutine() -> None:
    import app.live2d as live2d_mod

    conn = live2d_mod.Live2DConnection()
    original_schedule = asyncio.run_coroutine_threadsafe
    original_ensure = conn._ensure_background_loop

    async def pending() -> None:
        return None

    coroutine = pending()
    try:
        conn._ensure_background_loop = lambda: object()

        def fail_schedule(_coroutine, _loop):
            raise RuntimeError("loop stopped before scheduling")

        asyncio.run_coroutine_threadsafe = fail_schedule
        try:
            conn._run_on_background(coroutine, timeout=1)
            raise AssertionError("scheduling on a stopped loop should fail")
        except RuntimeError as exc:
            assert "loop stopped" in str(exc)
        assert coroutine.cr_frame is None
    finally:
        asyncio.run_coroutine_threadsafe = original_schedule
        conn._ensure_background_loop = original_ensure
        if coroutine.cr_frame is not None:
            coroutine.close()


def verify_disconnect_run_failure_closes_coroutine() -> None:
    import app.live2d as live2d_mod

    conn = live2d_mod.Live2DConnection()
    original_run = asyncio.run
    captured = []
    try:
        def fail_run(coroutine):
            captured.append(coroutine)
            raise RuntimeError("running event loop")

        asyncio.run = fail_run
        conn.disconnect()
        assert len(captured) == 1
        assert captured[0].cr_frame is None
    finally:
        asyncio.run = original_run
        for coroutine in captured:
            if coroutine.cr_frame is not None:
                coroutine.close()


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
    import app.embodiment as emb

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
        server.live2d_refresh(user)
        raise AssertionError("should fail capability refresh when live2d is disabled")
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
        server.live2d_lip_sync(server.Live2DLipSyncRequest(value=0.5), user)
        raise AssertionError("should fail lip sync when live2d is disabled")
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

    class RefreshConnection:
        is_connected = True
        is_authenticated = True
        injected: list[tuple[str, float]] = []

        def refresh_capabilities(self) -> bool:
            return True

        def get_connection_status(self) -> dict:
            return {"available_parameters": [{"name": "MouthOpen"}]}

        def inject_parameter(self, parameter: str, value: float) -> bool:
            self.injected.append((parameter, value))
            return True

    original_server_enabled = server.live2d_enabled
    original_connection = emb.get_live2d_connection
    original_status = server.live2d_connection_status
    original_config = server.load_live2d_config
    try:
        server.live2d_enabled = lambda: True
        emb.get_live2d_connection = lambda: RefreshConnection()
        server.live2d_connection_status = lambda: {
            "enabled": True,
            "connected": True,
            "authenticated": True,
            "current_model": {"modelID": "mio-main"},
        }
        server.load_live2d_config = lambda: {
            "enabled": True,
            "lip_sync_enabled": True,
            "lip_sync_parameter": "MouthOpen",
        }
        refreshed = server.live2d_refresh(user)
        assert refreshed["refreshed"] is True
        assert refreshed["status"]["current_model"]["modelID"] == "mio-main"
        lip_sync = server.live2d_lip_sync(server.Live2DLipSyncRequest(value=0.55), user)
        assert lip_sync["applied"] is True
        assert lip_sync["parameter"] == "MouthOpen"
        assert RefreshConnection.injected[-1] == ("MouthOpen", 0.55)
    finally:
        server.live2d_enabled = original_server_enabled
        emb.get_live2d_connection = original_connection
        server.live2d_connection_status = original_status
        server.load_live2d_config = original_config


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp, patch("app.live2d.load_config", return_value={}):
        database.DB_PATH = Path(tmp) / "phase5_live2d.db"
        database.init_db()
        user_id = seed_user()
        verify_live2d_config()
        verify_embodiment()
        verify_expression_mapper()
        verify_live2d_connection()
        verify_live2d_token_store()
        verify_live2d_auth_and_capabilities()
        verify_sync_connection_loop_lifetime()
        verify_live2d_autoconnect_lifecycle()
        verify_live2d_autoconnect_retries()
        verify_background_schedule_failure_closes_coroutine()
        verify_disconnect_run_failure_closes_coroutine()
        verify_vts_request_id_filtering()
        verify_vts_request_serialization()
        verify_vts_timeout_disconnects()
        verify_server_endpoints(user_id)
    print("Phase 5 Live2D embodiment verification passed")


if __name__ == "__main__":
    main()
