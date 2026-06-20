from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any

from .config import BASE_DIR, load_config


DEFAULT_LIVE2D_CONFIG: dict[str, Any] = {
    "enabled": False,
    "vts_ws_url": "ws://127.0.0.1:8002",
    "vts_plugin_name": "LINGEmbodiment",
    "expression_map": {
        "微笑": "Smile",
        "轻笑": "Smile",
        "担心": "Worried",
        "轻声": "Default",
        "停顿": "Default",
        "点头": "Nod",
    },
    "idle_expressions": ["Default", "Breathing"],
    "idle_expression": "",
    "listening_expression": "Listening",
    "speaking_expression": "Talking",
    "thinking_expression": "Thinking",
    "lip_sync_enabled": True,
    "lip_sync_parameter": "MouthOpen",
    "lip_sync_gain": 2.2,
}

LIVE2D_TOKEN_PATH = BASE_DIR / "data" / "live2d_auth_token.json"
PLUGIN_DEVELOPER = "LING"


def load_live2d_config() -> dict[str, Any]:
    config = load_config()
    live2d = config.get("live2d", {}) or {}
    if not isinstance(live2d, dict):
        live2d = {}
    merged = dict(DEFAULT_LIVE2D_CONFIG)
    for key, value in live2d.items():
        if key in merged:
            merged[key] = value
    idle_expression = str(live2d.get("idle_expression") or "").strip()
    if idle_expression:
        merged["idle_expressions"] = [idle_expression]
    merged["lip_sync_enabled"] = bool(merged.get("lip_sync_enabled", True))
    merged["lip_sync_parameter"] = str(merged.get("lip_sync_parameter") or "MouthOpen").strip() or "MouthOpen"
    try:
        merged["lip_sync_gain"] = max(0.1, min(float(merged.get("lip_sync_gain", 2.2)), 10.0))
    except (TypeError, ValueError):
        merged["lip_sync_gain"] = 2.2
    return merged


def live2d_enabled() -> bool:
    return bool(load_live2d_config().get("enabled", False))


class Live2DConnection:
    """Async WebSocket connection to VTube Studio API."""

    def __init__(self):
        self._config = load_live2d_config()
        self._ws = None
        self._connected = False
        self._authenticated = False
        self._connecting = False
        self._lock = threading.Lock()
        self._connect_lock = threading.Lock()
        self._last_error: str | None = None
        self._request_id = 0
        self._available_hotkeys: list[dict] = []
        self._available_expressions: list[dict] = []
        self._current_model: dict[str, Any] = {}
        self._available_models: list[dict[str, Any]] = []
        self._available_parameters: list[dict[str, Any]] = []
        self._capabilities_stale = True
        self._capabilities_updated_at = 0
        self._connection_loop: asyncio.AbstractEventLoop | None = None
        self._request_lock: asyncio.Lock | None = None
        self._background_loop: asyncio.AbstractEventLoop | None = None
        self._background_thread: threading.Thread | None = None
        self._background_ready = threading.Event()
        self._lifecycle_lock = threading.Lock()

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._connected

    @property
    def is_authenticated(self) -> bool:
        with self._lock:
            return self._authenticated

    @property
    def is_connecting(self) -> bool:
        with self._lock:
            return self._connecting

    @property
    def last_error(self) -> str | None:
        with self._lock:
            return self._last_error

    async def connect_async(self) -> bool:
        """Async connect to VTube Studio WebSocket."""
        if not live2d_enabled():
            self._last_error = "live2d is disabled in config"
            return False

        if self._ws is not None:
            await self.disconnect_async()

        self._connection_loop = asyncio.get_running_loop()
        self._request_lock = asyncio.Lock()
        self._config = load_live2d_config()
        url = self._config.get("vts_ws_url", "ws://127.0.0.1:8002")
        plugin_name = self._config.get("vts_plugin_name", "LINGEmbodiment")

        try:
            import websockets
        except ImportError:
            self._last_error = "websockets library not installed. Run: pip install websockets"
            with self._lock:
                self._connected = False
            return False

        try:
            self._ws = await websockets.connect(url, ping_interval=20, ping_timeout=10, close_timeout=5)
        except Exception as exc:
            self._last_error = f"WebSocket connection failed: {exc}"
            with self._lock:
                self._connected = False
            return False

        with self._lock:
            self._connected = True

        if await self._authenticate_with_vts(plugin_name):
            with self._lock:
                self._authenticated = True
            capabilities_refreshed = await self._refresh_capabilities_async()
            if capabilities_refreshed:
                self._last_error = None
            return True

        await self.disconnect_async()
        return False

    def connect(self) -> bool:
        """Connect on a persistent background loop used for the WebSocket lifetime."""
        if not live2d_enabled():
            return False
        if not self._connect_lock.acquire(blocking=False):
            return False
        with self._lock:
            self._connecting = True
        try:
            result = bool(self._run_on_background(self.connect_async(), timeout=25.0))
            if not result:
                self._stop_background_loop()
            return result
        except Exception as exc:
            self._last_error = str(exc)
            self._stop_background_loop()
            return False
        finally:
            with self._lock:
                self._connecting = False
            self._connect_lock.release()

    async def disconnect_async(self) -> None:
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        with self._lock:
            self._connected = False
            self._authenticated = False
            self._available_hotkeys = []
            self._available_expressions = []
            self._current_model = {}
            self._available_models = []
            self._available_parameters = []
            self._capabilities_stale = True
            self._capabilities_updated_at = 0
        self._request_lock = None
        self._connection_loop = None

    def disconnect(self) -> None:
        acquired = self._connect_lock.acquire(timeout=30.0)
        if not acquired:
            self._last_error = "Live2D disconnect timed out while a connection attempt was active"
            return
        try:
            if self._background_loop and self._background_loop.is_running():
                self._run_on_background(self.disconnect_async(), timeout=10.0)
            elif self._connection_loop and self._connection_loop.is_running():
                self._last_error = "disconnect_async must be used for an externally managed Live2D event loop"
            else:
                coroutine = self.disconnect_async()
                try:
                    asyncio.run(coroutine)
                except Exception:
                    coroutine.close()
                    raise
        except Exception:
            pass
        finally:
            self._stop_background_loop()
            self._connect_lock.release()

    def _run_background_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._background_loop = loop
        self._background_ready.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()

    def _ensure_background_loop(self) -> asyncio.AbstractEventLoop:
        with self._lifecycle_lock:
            loop = self._background_loop
            thread = self._background_thread
            if loop and loop.is_running() and thread and thread.is_alive():
                return loop
            self._background_ready = threading.Event()
            thread = threading.Thread(target=self._run_background_loop, name="ling-live2d-vts", daemon=True)
            self._background_thread = thread
            thread.start()

        if not self._background_ready.wait(timeout=3.0):
            raise RuntimeError("Live2D background event loop did not start")
        loop = self._background_loop
        if loop is None or not loop.is_running():
            raise RuntimeError("Live2D background event loop is unavailable")
        return loop

    def _run_on_background(self, coroutine, timeout: float):
        try:
            loop = self._ensure_background_loop()
        except Exception:
            coroutine.close()
            raise
        try:
            future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        except Exception:
            coroutine.close()
            raise
        try:
            return future.result(timeout=timeout)
        except Exception:
            future.cancel()
            raise

    def _stop_background_loop(self) -> None:
        with self._lifecycle_lock:
            loop = self._background_loop
            thread = self._background_thread
        if loop and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=3.0)
        with self._lifecycle_lock:
            if self._background_thread is thread:
                self._background_thread = None
            if self._background_loop is loop:
                self._background_loop = None

    async def set_expression_async(self, expression_name: str) -> bool:
        """Set a Live2D expression by name."""
        if not self._connected or not self._authenticated:
            return False

        if not expression_name or expression_name == "Default":
            return await self._deactivate_active_expressions_async()

        expression_file = self._find_expression_file(expression_name)
        if not expression_file:
            return await self.trigger_motion_async(expression_name)

        if not await self._deactivate_active_expressions_async(except_file=expression_file):
            return False

        result = await self._send_vts_request("ExpressionActivationRequest", {
            "expressionFile": expression_file,
            "active": True,
        })

        if result is False:
            return False
        applied = result is not None
        if applied:
            self._mark_expression_active(expression_file)
        return applied

    def set_expression(self, expression_name: str) -> bool:
        """Sync wrapper for set_expression_async."""
        if not self.is_connected or not self.is_authenticated:
            return False
        try:
            if self._connection_loop is not self._background_loop or not self._background_loop:
                self._last_error = "set_expression_async must be used for an externally managed Live2D event loop"
                return False
            return bool(self._run_on_background(self.set_expression_async(expression_name), timeout=15.0))
        except Exception as exc:
            self._last_error = f"Live2D expression failed: {exc}"
            return False

    async def trigger_motion_async(self, motion_name: str) -> bool:
        """Trigger a motion/animation."""
        if not self._connected or not self._authenticated:
            return False

        hotkey_id = self._find_hotkey_id(motion_name)
        if hotkey_id:
            result = await self._send_vts_request("HotkeyTriggerRequest", {
                "hotkeyID": hotkey_id,
            })
            return result is not None and result is not False

        return False

    def trigger_motion(self, motion_name: str) -> bool:
        """Sync wrapper for trigger_motion_async."""
        if not self.is_connected or not self.is_authenticated:
            return False
        try:
            if self._connection_loop is not self._background_loop or not self._background_loop:
                self._last_error = "trigger_motion_async must be used for an externally managed Live2D event loop"
                return False
            return bool(self._run_on_background(self.trigger_motion_async(motion_name), timeout=15.0))
        except Exception as exc:
            self._last_error = f"Live2D motion failed: {exc}"
            return False

    async def inject_parameter_async(self, parameter_name: str, value: float, weight: float = 1.0) -> bool:
        if not self._connected or not self._authenticated:
            return False
        normalized = str(parameter_name or "").strip()
        if not normalized or not self._find_parameter(normalized):
            self._last_error = f"VTS input parameter is unavailable: {normalized or 'unset'}"
            return False
        result = await self._send_vts_request("InjectParameterDataRequest", {
            "faceFound": False,
            "mode": "set",
            "parameterValues": [{
                "id": normalized,
                "value": max(0.0, min(float(value), 1.0)),
                "weight": max(0.0, min(float(weight), 1.0)),
            }],
        })
        return result is not None and result is not False

    def inject_parameter(self, parameter_name: str, value: float, weight: float = 1.0) -> bool:
        if not self.is_connected or not self.is_authenticated:
            return False
        try:
            if self._connection_loop is not self._background_loop or not self._background_loop:
                self._last_error = "inject_parameter_async must be used for an externally managed Live2D event loop"
                return False
            return bool(self._run_on_background(
                self.inject_parameter_async(parameter_name, value, weight),
                timeout=5.0,
            ))
        except Exception as exc:
            self._last_error = f"Live2D parameter injection failed: {exc}"
            return False

    async def refresh_capabilities_async(self) -> bool:
        if not self._connected or not self._authenticated:
            return False
        refreshed = await self._refresh_capabilities_async()
        if refreshed and self.is_connected and self.is_authenticated:
            self._last_error = None
            return True
        return False

    def refresh_capabilities(self) -> bool:
        if not self.is_connected or not self.is_authenticated:
            return False
        try:
            if self._connection_loop is not self._background_loop or not self._background_loop:
                self._last_error = "refresh_capabilities_async must be used for an externally managed Live2D event loop"
                return False
            return bool(self._run_on_background(self.refresh_capabilities_async(), timeout=30.0))
        except Exception as exc:
            self._last_error = f"Live2D capability refresh failed: {exc}"
            return False

    async def _send_vts_request(self, message_type: str, data: dict | None = None) -> dict | None | bool:
        """Send a VTube Studio API request and return the response data."""
        if not self._ws:
            return None

        if self._request_lock is None:
            self._request_lock = asyncio.Lock()
        async with self._request_lock:
            return await self._send_vts_request_locked(message_type, data)

    async def _send_vts_request_locked(self, message_type: str, data: dict | None = None) -> dict | None | bool:
        """Serialize request/response pairs because VTS uses one shared WebSocket."""
        if not self._ws:
            return None

        with self._lock:
            self._request_id += 1
            request_id = str(self._request_id)

        request = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": request_id,
            "messageType": message_type,
            "data": data or {},
        }

        try:
            await self._ws.send(json.dumps(request, ensure_ascii=False))
        except Exception as exc:
            self._last_error = f"WebSocket send failed: {exc}"
            await self.disconnect_async()
            return False

        try:
            deadline = time.monotonic() + 10
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._last_error = "VTS request timed out"
                    await self.disconnect_async()
                    return False
                try:
                    raw = await asyncio.wait_for(self._ws.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    self._last_error = "VTS request timed out"
                    await self.disconnect_async()
                    return False

                response = json.loads(raw)
                response_request_id = response.get("requestID")
                if response_request_id and str(response_request_id) != request_id:
                    continue
                if not response_request_id and response.get("messageType") not in {"APIError", f"{message_type}Response"}:
                    continue
                if response.get("messageType") == "APIError":
                    self._last_error = response.get("data", {}).get("message", "Unknown VTS error")
                    return None
                return response.get("data", {})
        except Exception as exc:
            self._last_error = f"VTS response error: {exc}"
            await self.disconnect_async()
            return False

    async def _authenticate_with_vts(self, plugin_name: str) -> bool:
        token = self._load_auth_token()
        if token and await self._send_authentication_request(plugin_name, token):
            return True

        token_result = await self._send_vts_request("AuthenticationTokenRequest", {
            "pluginName": plugin_name,
            "pluginDeveloper": PLUGIN_DEVELOPER,
        })
        if not token_result or token_result is False:
            self._last_error = "VTS token request failed. Enable the VTube Studio plugin API and accept the authorization prompt."
            return False

        token = token_result.get("authenticationToken")
        if not token:
            self._last_error = f"VTS token response did not include authenticationToken: {token_result}"
            return False

        self._save_auth_token(token)
        if await self._send_authentication_request(plugin_name, token):
            return True

        self._last_error = "VTS authentication failed after token was granted"
        return False

    async def _send_authentication_request(self, plugin_name: str, token: str) -> bool:
        auth_result = await self._send_vts_request("AuthenticationRequest", {
            "pluginName": plugin_name,
            "pluginDeveloper": PLUGIN_DEVELOPER,
            "authenticationToken": token,
        })
        if auth_result and auth_result is not False and auth_result.get("authenticated"):
            return True
        if auth_result and auth_result is not False and auth_result.get("reason"):
            self._last_error = f"VTS authentication failed: {auth_result.get('reason')}"
        else:
            self._last_error = f"VTS authentication failed: {auth_result}"
        return False

    async def _refresh_capabilities_async(self) -> bool:
        current_model = await self._send_vts_request("CurrentModelRequest", {})
        if current_model is None or current_model is False:
            with self._lock:
                self._capabilities_stale = True
            return False
        if not isinstance(current_model, dict):
            self._last_error = "VTS current model response had an invalid shape"
            with self._lock:
                self._capabilities_stale = True
            return False

        hotkeys = await self._send_vts_request("HotkeysInCurrentModelRequest", {})
        if hotkeys is None or hotkeys is False:
            with self._lock:
                self._capabilities_stale = True
            return False

        expressions = await self._send_vts_request("ExpressionStateRequest", {
            "details": True,
        })
        if expressions is None or expressions is False:
            with self._lock:
                self._capabilities_stale = True
            return False

        available_models = await self._send_vts_request("AvailableModelsRequest", {})
        if available_models is None or available_models is False:
            with self._lock:
                self._capabilities_stale = True
            return False

        parameters = await self._send_vts_request("InputParameterListRequest", {})
        if parameters is None or parameters is False:
            with self._lock:
                self._capabilities_stale = True
            return False

        if (
            not isinstance(hotkeys, dict)
            or not isinstance(expressions, dict)
            or not isinstance(available_models, dict)
            or not isinstance(parameters, dict)
        ):
            self._last_error = "VTS capability response had an invalid shape"
            with self._lock:
                self._capabilities_stale = True
            return False

        hotkey_items = hotkeys.get("availableHotkeys") or hotkeys.get("hotkeys") or []
        expression_items = expressions.get("expressions") or []
        model_items = available_models.get("availableModels") or available_models.get("models") or []
        default_parameters = parameters.get("defaultParameters") or []
        custom_parameters = parameters.get("customParameters") or []
        if (
            not isinstance(hotkey_items, list)
            or not isinstance(expression_items, list)
            or not isinstance(model_items, list)
            or not isinstance(default_parameters, list)
            or not isinstance(custom_parameters, list)
        ):
            self._last_error = "VTS capability response had an invalid shape"
            with self._lock:
                self._capabilities_stale = True
            return False

        with self._lock:
            self._current_model = self._compact_model(current_model)
            self._available_hotkeys = [item for item in hotkey_items if isinstance(item, dict)]
            self._available_expressions = [item for item in expression_items if isinstance(item, dict)]
            self._available_models = [self._compact_model(item) for item in model_items if isinstance(item, dict)]
            self._available_parameters = [
                self._compact_parameter(item)
                for item in [*default_parameters, *custom_parameters]
                if isinstance(item, dict)
            ]
            self._capabilities_stale = False
            self._capabilities_updated_at = int(time.time())
        return True

    def _load_auth_token(self) -> str | None:
        try:
            with LIVE2D_TOKEN_PATH.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

        if not isinstance(payload, dict):
            return None
        if payload.get("plugin_name") != self._config.get("vts_plugin_name", "LINGEmbodiment"):
            return None
        if payload.get("vts_ws_url") != self._config.get("vts_ws_url", "ws://127.0.0.1:8002"):
            return None
        token = payload.get("authentication_token")
        return token if isinstance(token, str) and token else None

    def _save_auth_token(self, token: str) -> None:
        payload = {
            "plugin_name": self._config.get("vts_plugin_name", "LINGEmbodiment"),
            "plugin_developer": PLUGIN_DEVELOPER,
            "vts_ws_url": self._config.get("vts_ws_url", "ws://127.0.0.1:8002"),
            "authentication_token": token,
            "created_at": int(time.time()),
        }
        try:
            LIVE2D_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            with LIVE2D_TOKEN_PATH.open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except OSError as exc:
            self._last_error = f"Could not save VTS token: {exc}"

    def _find_hotkey_id(self, name: str) -> str | None:
        if not name:
            return None
        target = name.lower()
        for hk in self._available_hotkeys:
            hotkey_id = hk.get("hotkeyID")
            candidates = [
                hk.get("name"),
                hk.get("file"),
                hk.get("description"),
                hotkey_id,
            ]
            for candidate in candidates:
                if isinstance(candidate, str) and candidate.lower() == target:
                    return hotkey_id if isinstance(hotkey_id, str) else None
        return None

    def _find_expression_file(self, name: str) -> str | None:
        target = str(name or "").strip().lower()
        if not target:
            return None
        for expression in self._available_expressions:
            expression_file = expression.get("file") or expression.get("expressionFile")
            candidates = [expression.get("name"), expression_file]
            if isinstance(expression_file, str) and expression_file.lower().endswith(".exp3.json"):
                candidates.append(expression_file[:-10])
            if any(isinstance(candidate, str) and candidate.strip().lower() == target for candidate in candidates):
                return expression_file if isinstance(expression_file, str) and expression_file else None
        if self._available_expressions:
            return None
        # Some VTS models expose actions only as hotkeys and return no
        # ExpressionState entries. Do not invent an expression filename when
        # the requested action is a discovered hotkey.
        if self._find_hotkey_id(name):
            return None
        return name if target.endswith(".exp3.json") else f"{name}.exp3.json"

    def _find_parameter(self, name: str) -> dict[str, Any] | None:
        target = str(name or "").strip().casefold()
        with self._lock:
            for parameter in self._available_parameters:
                if str(parameter.get("name") or "").strip().casefold() == target:
                    return dict(parameter)
        return None

    async def _deactivate_active_expressions_async(self, except_file: str | None = None) -> bool:
        active_files = []
        for expression in self._available_expressions:
            expression_file = expression.get("file") or expression.get("expressionFile")
            if expression.get("active") and isinstance(expression_file, str) and expression_file != except_file:
                active_files.append(expression_file)
        for expression_file in active_files:
            result = await self._send_vts_request("ExpressionActivationRequest", {
                "expressionFile": expression_file,
                "active": False,
            })
            if result is None or result is False:
                return False
            self._mark_expression_inactive(expression_file)
        return True

    def _mark_expression_active(self, expression_file: str) -> None:
        with self._lock:
            for expression in self._available_expressions:
                current_file = expression.get("file") or expression.get("expressionFile")
                if isinstance(current_file, str):
                    expression["active"] = current_file == expression_file

    def _mark_expression_inactive(self, expression_file: str) -> None:
        with self._lock:
            for expression in self._available_expressions:
                current_file = expression.get("file") or expression.get("expressionFile")
                if current_file == expression_file:
                    expression["active"] = False

    @staticmethod
    def _compact_model(model: dict[str, Any]) -> dict[str, str | bool]:
        compact: dict[str, str | bool] = {}
        for key in ("modelID", "modelName", "vtsModelName", "modelFileName"):
            value = model.get(key)
            if isinstance(value, str) and value.strip():
                compact[key] = value.strip()
        if "modelLoaded" in model:
            compact["modelLoaded"] = bool(model.get("modelLoaded"))
        return compact

    def get_connection_status(self) -> dict:
        config = load_live2d_config()
        with self._lock:
            return {
                "enabled": config.get("enabled", False),
                "connecting": self._connecting,
                "connected": self._connected,
                "authenticated": self._authenticated,
                "vts_ws_url": config.get("vts_ws_url", ""),
                "plugin_name": config.get("vts_plugin_name", ""),
                "last_error": self._last_error,
                "websockets_available": self._check_websockets_available(),
                "available_hotkey_count": len(self._available_hotkeys),
                "available_expression_count": len(self._available_expressions),
                "available_hotkeys": [self._compact_hotkey(item) for item in self._available_hotkeys[:40]],
                "available_expressions": [self._compact_expression(item) for item in self._available_expressions[:40]],
                "available_model_count": len(self._available_models),
                "current_model": dict(self._current_model),
                "available_models": [dict(model) for model in self._available_models[:12]],
                "available_parameter_count": len(self._available_parameters),
                "available_parameters": [dict(item) for item in self._available_parameters[:120]],
                "lip_sync_enabled": bool(config.get("lip_sync_enabled", True)),
                "lip_sync_parameter": str(config.get("lip_sync_parameter") or "MouthOpen"),
                "lip_sync_gain": float(config.get("lip_sync_gain") or 2.2),
                "capabilities_stale": self._capabilities_stale,
                "capabilities_updated_at": self._capabilities_updated_at,
            }

    @staticmethod
    def _compact_hotkey(hotkey: dict[str, Any]) -> dict[str, str]:
        return {
            key: value.strip()
            for key in ("name", "hotkeyID", "file", "description")
            if isinstance((value := hotkey.get(key)), str) and value.strip()
        }

    @staticmethod
    def _compact_expression(expression: dict[str, Any]) -> dict[str, str | bool]:
        compact: dict[str, str | bool] = {
            key: value.strip()
            for key in ("name", "file", "expressionFile")
            if isinstance((value := expression.get(key)), str) and value.strip()
        }
        compact["active"] = bool(expression.get("active"))
        return compact

    @staticmethod
    def _compact_parameter(parameter: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key in ("name", "addedBy", "value", "min", "max", "defaultValue")
            if (value := parameter.get(key)) is not None
        }

    @staticmethod
    def _check_websockets_available() -> bool:
        try:
            import websockets
            return True
        except ImportError:
            return False
