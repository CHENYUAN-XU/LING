from __future__ import annotations

import json
import os
import sys
import hashlib
import socket
import threading
import time
from typing import Any, Callable
from typing import Dict, List

import requests

from .config import load_config
from .database import get_db, now_ts


Message = Dict[str, str]
_LLM_PROBE_CACHE: dict[str, dict[str, Any]] = {}
_LLM_PROBE_CACHE_LOCK = threading.Lock()
LLM_VERIFICATION_TTL_SECONDS = 7 * 24 * 60 * 60


class LLMProviderError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.user_message = "服务暂时繁忙，请稍后再试。"


class LLMStreamCancelled(RuntimeError):
    """Raised when a local client interrupts an in-flight streamed reply."""


def messages_to_prompt(messages: List[Message]) -> str:
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "user").upper()
        content = msg.get("content", "")
        parts.append(f"[{role}]\n{content}")
    parts.append("[ASSISTANT]\n")
    return "\n\n".join(parts)


def _get_env(name: str) -> str | None:
    value = os.getenv(name)
    if value:
        return value
    if sys.platform != "win32":
        return None
    try:
        import winreg

        for root, path in (
            (winreg.HKEY_CURRENT_USER, "Environment"),
            (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        ):
            try:
                with winreg.OpenKey(root, path) as key:
                    value, _ = winreg.QueryValueEx(key, name)
                    if value:
                        return str(value)
            except OSError:
                continue
    except Exception:
        return None
    return None


def _call_ollama(messages: List[Message], llm_config: dict) -> str:
    base_url = str(llm_config.get("base_url") or "http://localhost:11434").rstrip("/")
    payload = {
        "model": llm_config.get("model") or "qwen2.5:3b",
        "prompt": messages_to_prompt(messages),
        "stream": False,
        "options": {
            "temperature": float(llm_config.get("temperature", 0.75)),
        },
    }

    try:
        response = requests.post(f"{base_url}/api/generate", json=payload, timeout=120)
        response.raise_for_status()
    except requests.RequestException as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        raise LLMProviderError(f"ollama request failed with status {status_code or 'unknown'}", status_code=status_code) from exc
    data = response.json()
    return str(data.get("response", "")).strip()


def _call_chat_completions(
    messages: List[Message],
    llm_config: dict,
    *,
    provider_name: str,
    env_key: str,
    default_base_url: str,
    default_model: str,
    include_temperature: bool = True,
) -> str:
    api_key = _get_env(str(llm_config.get("api_key_env") or env_key))
    if not api_key:
        raise RuntimeError(f"{env_key} is not set, but config.yaml selects provider: {provider_name}")

    configured_base_url = str(llm_config.get("base_url") or "").rstrip("/")
    if not configured_base_url or configured_base_url == "http://localhost:11434":
        base_url = default_base_url.rstrip("/")
    else:
        base_url = configured_base_url
    payload = {
        "model": llm_config.get("model") or default_model,
        "messages": messages,
    }
    if include_temperature:
        payload["temperature"] = float(llm_config.get("temperature", 0.75))
    if llm_config.get("max_tokens"):
        payload["max_tokens"] = int(llm_config.get("max_tokens") or 0)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=float(llm_config.get("timeout", 60)),
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        raise LLMProviderError(f"{provider_name} request failed with status {status_code or 'unknown'}", status_code=status_code) from exc
    data = response.json()
    return str(data["choices"][0]["message"]["content"]).strip()


def _call_chat_completions_stream(
    messages: List[Message],
    llm_config: dict,
    *,
    provider_name: str,
    env_key: str,
    default_base_url: str,
    default_model: str,
    on_delta: Callable[[str], None],
    should_cancel: Callable[[], bool] | None = None,
    include_temperature: bool = True,
) -> str:
    """Stream an OpenAI-compatible chat completion and return its full text."""
    api_key = _get_env(str(llm_config.get("api_key_env") or env_key))
    if not api_key:
        raise RuntimeError(f"{env_key} is not set, but config.yaml selects provider: {provider_name}")
    configured_base_url = str(llm_config.get("base_url") or "").rstrip("/")
    base_url = default_base_url.rstrip("/") if not configured_base_url or configured_base_url == "http://localhost:11434" else configured_base_url
    payload: dict[str, Any] = {
        "model": llm_config.get("model") or default_model,
        "messages": messages,
        "stream": True,
    }
    if include_temperature:
        payload["temperature"] = float(llm_config.get("temperature", 0.75))
    if llm_config.get("max_tokens"):
        payload["max_tokens"] = int(llm_config.get("max_tokens") or 0)
    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=float(llm_config.get("timeout", 60)),
            stream=True,
        )
        response.raise_for_status()
        # Some OpenAI-compatible streaming gateways omit a charset. Requests then
        # falls back to ISO-8859-1, which corrupts UTF-8 Chinese SSE deltas.
        response.encoding = "utf-8"
    except requests.RequestException as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        raise LLMProviderError(f"{provider_name} stream request failed with status {status_code or 'unknown'}", status_code=status_code) from exc

    fragments: list[str] = []
    try:
        # `requests` defaults to a 512-byte read buffer here.  A short Chinese
        # reply often fits entirely inside that buffer, which makes an upstream
        # SSE stream look like one non-streaming final answer.  Keep the buffer
        # tiny so every completed provider SSE line is forwarded immediately.
        for raw_line in response.iter_lines(chunk_size=1, decode_unicode=True):
            if should_cancel and should_cancel():
                raise LLMStreamCancelled("chat stream cancelled")
            line = str(raw_line or "").strip()
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                event = json.loads(data)
                delta = event.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "") if isinstance(delta, dict) else ""
            except (IndexError, TypeError, ValueError):
                continue
            if isinstance(content, str) and content:
                fragments.append(content)
                on_delta(content)
    finally:
        response.close()
    if should_cancel and should_cancel():
        raise LLMStreamCancelled("chat stream cancelled")
    return "".join(fragments).strip()


def _call_openai(messages: List[Message], llm_config: dict) -> str:
    return _call_chat_completions(
        messages,
        llm_config,
        provider_name="openai",
        env_key="OPENAI_API_KEY",
        default_base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
    )


def _call_deepseek(messages: List[Message], llm_config: dict) -> str:
    return _call_chat_completions(
        messages,
        llm_config,
        provider_name="deepseek",
        env_key="DEEPSEEK_API_KEY",
        default_base_url="https://api.deepseek.com/v1",
        default_model="deepseek-v4-flash",
    )


def _call_kimi(messages: List[Message], llm_config: dict) -> str:
    return _call_chat_completions(
        messages,
        llm_config,
        provider_name="kimi",
        env_key="MOONSHOT_API_KEY",
        default_base_url="https://api.moonshot.ai/v1",
        default_model="kimi-k2.6",
        include_temperature=False,
    )


def call_llm_api(messages: List[Message], task: str = "default") -> str:
    llm_config = _llm_config_for_task(task)
    provider = str(llm_config.get("provider", "ollama")).lower()
    model = str(llm_config.get("model") or "")
    started = time.perf_counter()
    prompt_chars = sum(len(str(message.get("content", ""))) for message in messages)

    try:
        if provider == "ollama":
            response = _call_ollama(messages, llm_config)
        elif provider == "openai":
            response = _call_openai(messages, llm_config)
        elif provider == "deepseek":
            response = _call_deepseek(messages, llm_config)
        elif provider in {"kimi", "moonshot"}:
            response = _call_kimi(messages, llm_config)
        elif provider in {"openai_compatible", "compatible"} or llm_config.get("api_key_env"):
            response = _call_compatible_provider(messages, llm_config)
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")
    except Exception as exc:
        _record_llm_call(
            task=task,
            provider=provider,
            model=model,
            status="failed",
            prompt_chars=prompt_chars,
            response_chars=0,
            duration_ms=_elapsed_ms(started),
            error_text=f"{type(exc).__name__}: {exc}",
        )
        raise

    _record_llm_call(
        task=task,
        provider=provider,
        model=model,
        status="success",
        prompt_chars=prompt_chars,
        response_chars=len(response),
        duration_ms=_elapsed_ms(started),
    )
    _mark_llm_verified(task, llm_config)
    return response


def call_llm_api_stream(
    messages: List[Message],
    on_delta: Callable[[str], None],
    task: str = "default",
    should_cancel: Callable[[], bool] | None = None,
) -> str:
    """Use provider streaming when supported; callers still receive the final full reply."""
    llm_config = _llm_config_for_task(task)
    provider = str(llm_config.get("provider", "ollama")).lower()
    model = str(llm_config.get("model") or "")
    started = time.perf_counter()
    prompt_chars = sum(len(str(message.get("content", ""))) for message in messages)
    try:
        if provider == "openai":
            response = _call_chat_completions_stream(messages, llm_config, provider_name="openai", env_key="OPENAI_API_KEY", default_base_url="https://api.openai.com/v1", default_model="gpt-4o-mini", on_delta=on_delta, should_cancel=should_cancel)
        elif provider == "deepseek":
            response = _call_chat_completions_stream(messages, llm_config, provider_name="deepseek", env_key="DEEPSEEK_API_KEY", default_base_url="https://api.deepseek.com/v1", default_model="deepseek-v4-flash", on_delta=on_delta, should_cancel=should_cancel)
        elif provider in {"kimi", "moonshot"}:
            response = _call_chat_completions_stream(messages, llm_config, provider_name="kimi", env_key="MOONSHOT_API_KEY", default_base_url="https://api.moonshot.ai/v1", default_model="kimi-k2.6", on_delta=on_delta, should_cancel=should_cancel, include_temperature=False)
        elif provider in {"openai_compatible", "compatible"} or llm_config.get("api_key_env"):
            response = _call_chat_completions_stream(messages, llm_config, provider_name=provider, env_key=str(llm_config.get("api_key_env") or "OPENAI_API_KEY"), default_base_url=str(llm_config.get("base_url") or "https://api.openai.com/v1"), default_model=str(llm_config.get("model") or "gpt-4o-mini"), on_delta=on_delta, should_cancel=should_cancel)
        else:
            # Preserve a useful response for non-streaming local providers.
            response = call_llm_api(messages, task=task)
            if should_cancel and should_cancel():
                raise LLMStreamCancelled("chat stream cancelled")
            if response:
                on_delta(response)
            return response
    except Exception as exc:
        _record_llm_call(task=task, provider=provider, model=model, status="failed", prompt_chars=prompt_chars, response_chars=0, duration_ms=_elapsed_ms(started), error_text=f"{type(exc).__name__}: {exc}")
        raise
    _record_llm_call(task=task, provider=provider, model=model, status="success", prompt_chars=prompt_chars, response_chars=len(response), duration_ms=_elapsed_ms(started))
    _mark_llm_verified(task, llm_config)
    return response


def llm_runtime_status(task: str = "chat") -> dict[str, Any]:
    llm_config = _llm_config_for_task(task)
    provider = str(llm_config.get("provider", "ollama")).lower()
    model = str(llm_config.get("model") or "")
    base_url = str(llm_config.get("base_url") or "").rstrip("/")
    api_key_env = str(llm_config.get("api_key_env") or _default_api_key_env(provider) or "")
    requires_api_key = provider != "ollama" and bool(api_key_env)
    configured = True
    missing: list[str] = []
    if requires_api_key and not _get_env(api_key_env):
        configured = False
        missing.append(api_key_env)
    verification = _cached_llm_verification(llm_config, provider, model, base_url, api_key_env) if configured else None
    return {
        "task": task,
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "api_key_env": api_key_env,
        "requires_api_key": requires_api_key,
        "configured": configured,
        "verified": bool(verification and verification.get("ok")),
        "verification": verification or {"state": "unverified", "checked_at": None},
        "missing": missing,
    }


def probe_llm_runtime(task: str = "chat", timeout: float = 8.0) -> dict[str, Any]:
    llm_config = _llm_config_for_task(task)
    provider = str(llm_config.get("provider", "ollama")).lower()
    model = str(llm_config.get("model") or "").strip()
    configured_base_url = str(llm_config.get("base_url") or "").rstrip("/")
    api_key_env = str(llm_config.get("api_key_env") or _default_api_key_env(provider) or "")
    requires_api_key = provider != "ollama" and bool(api_key_env)
    api_key = _get_env(api_key_env) if requires_api_key else None
    checked_at = int(time.time())

    if requires_api_key and not api_key:
        return {
            "ok": False,
            "state": "failed",
            "provider": provider,
            "model": model,
            "checked_at": checked_at,
            "status_code": None,
            "model_available": None,
            "error": f"missing API key environment variable: {api_key_env}",
        }

    if provider == "ollama":
        base_url = configured_base_url or "http://localhost:11434"
        url = f"{base_url}/api/tags"
        headers: dict[str, str] = {}
    else:
        base_url = _effective_chat_base_url(provider, configured_base_url)
        url = f"{base_url}/models"
        headers = {"Authorization": f"Bearer {api_key}"}

    try:
        response = requests.get(url, headers=headers, timeout=max(1.0, min(float(timeout), 15.0)))
        response.raise_for_status()
        payload = response.json()
        available_models = _probe_model_ids(provider, payload)
        model_available = not model or model in available_models
        result = {
            "ok": bool(model_available),
            "state": "verified" if model_available else "failed",
            "provider": provider,
            "model": model,
            "checked_at": checked_at,
            "status_code": int(response.status_code),
            "model_available": bool(model_available),
            "error": None if model_available else f"configured model is not available: {model}",
        }
    except requests.RequestException as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        result = {
            "ok": False,
            "state": "failed",
            "provider": provider,
            "model": model,
            "checked_at": checked_at,
            "status_code": int(status_code) if status_code is not None else None,
            "model_available": None,
            "error": _probe_request_error(exc),
        }
    except (TypeError, ValueError, KeyError) as exc:
        result = {
            "ok": False,
            "state": "failed",
            "provider": provider,
            "model": model,
            "checked_at": checked_at,
            "status_code": None,
            "model_available": None,
            "error": f"invalid model-list response: {type(exc).__name__}",
        }

    _store_llm_verification(llm_config, provider, model, configured_base_url, api_key_env, result)
    return dict(result)


def _probe_request_error(exc: requests.RequestException) -> str:
    """Keep network failures actionable without exposing raw URLs or headers."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status is not None:
        hint = "check the API key and account permissions" if status in {401, 403} else "retry later or check the provider status"
        return f"Model connection check failed: HTTP {status}; {hint}."
    if isinstance(exc, requests.exceptions.SSLError):
        return "Model connection check failed: TLS certificate error; check system time, certificates and proxy settings."
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return "Model connection check failed: connection timed out; check the network and configured base URL, then retry."
    if isinstance(exc, requests.exceptions.ReadTimeout):
        return "Model connection check failed: response timed out; the provider did not reply in time. Retry."
    if isinstance(exc, requests.exceptions.Timeout):
        return "Model connection check failed: request timed out; retry."
    pending = [exc]
    seen: set[int] = set()
    while pending:
        error = pending.pop()
        if id(error) in seen:
            continue
        seen.add(id(error))
        if isinstance(error, socket.gaierror) or type(error).__name__ == "NameResolutionError":
            return "Model connection check failed: DNS lookup failed; check the configured hostname and network."
        pending.extend(value for value in (error.__cause__, error.__context__, getattr(error, "reason", None), *error.args) if isinstance(value, BaseException))
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "Model connection check failed: could not connect; check the base URL, network and proxy settings."
    return "Model connection check failed: invalid network response; retry."


def _probe_model_ids(provider: str, payload: Any) -> set[str]:
    if not isinstance(payload, dict):
        raise ValueError("model-list response must be an object")
    items = payload.get("models") if provider == "ollama" else payload.get("data")
    if not isinstance(items, list):
        raise ValueError("model-list response does not contain a list")
    result: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        value = item.get("name") or item.get("model") if provider == "ollama" else item.get("id")
        if isinstance(value, str) and value.strip():
            result.add(value.strip())
    return result


def _effective_chat_base_url(provider: str, configured_base_url: str) -> str:
    if configured_base_url and configured_base_url != "http://localhost:11434":
        return configured_base_url
    return {
        "openai": "https://api.openai.com/v1",
        "deepseek": "https://api.deepseek.com/v1",
        "kimi": "https://api.moonshot.ai/v1",
        "moonshot": "https://api.moonshot.ai/v1",
    }.get(provider, configured_base_url).rstrip("/")


def _llm_probe_cache_key(
    llm_config: dict[str, Any],
    provider: str,
    model: str,
    base_url: str,
    api_key_env: str,
) -> str:
    api_key = _get_env(api_key_env) if api_key_env else ""
    key_fingerprint = hashlib.sha256(str(api_key or "").encode("utf-8")).hexdigest()[:16]
    material = "|".join((provider, model, base_url, api_key_env, key_fingerprint))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _cached_llm_verification(
    llm_config: dict[str, Any],
    provider: str,
    model: str,
    base_url: str,
    api_key_env: str,
) -> dict[str, Any] | None:
    key = _llm_probe_cache_key(llm_config, provider, model, base_url, api_key_env)
    with _LLM_PROBE_CACHE_LOCK:
        result = _LLM_PROBE_CACHE.get(key)
    if result and _llm_verification_is_fresh(result):
        return dict(result)
    if result:
        with _LLM_PROBE_CACHE_LOCK:
            _LLM_PROBE_CACHE.pop(key, None)

    try:
        with get_db() as db:
            row = db.execute(
                """
                SELECT state, checked_at, status_code, model_available, error_text
                FROM llm_route_verifications
                WHERE route_key = ?
                """,
                (key,),
            ).fetchone()
    except Exception:
        row = None
    if not row:
        return None
    persisted = {
        "ok": str(row["state"]) == "verified",
        "state": str(row["state"]),
        "provider": provider,
        "model": model,
        "checked_at": int(row["checked_at"] or 0),
        "status_code": row["status_code"],
        "model_available": None if row["model_available"] is None else bool(row["model_available"]),
        "error": str(row["error_text"] or "") or None,
    }
    if not _llm_verification_is_fresh(persisted):
        return None
    with _LLM_PROBE_CACHE_LOCK:
        _LLM_PROBE_CACHE[key] = dict(persisted)
    return persisted


def _store_llm_verification(
    llm_config: dict[str, Any],
    provider: str,
    model: str,
    base_url: str,
    api_key_env: str,
    result: dict[str, Any],
) -> None:
    key = _llm_probe_cache_key(llm_config, provider, model, base_url, api_key_env)
    safe = {
        field: result.get(field)
        for field in ("ok", "state", "provider", "model", "checked_at", "status_code", "model_available", "error")
    }
    with _LLM_PROBE_CACHE_LOCK:
        _LLM_PROBE_CACHE[key] = safe
    try:
        with get_db() as db:
            db.execute(
                """
                INSERT INTO llm_route_verifications (
                    route_key, provider, model, base_url, state, checked_at,
                    status_code, model_available, error_text
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(route_key) DO UPDATE SET
                    provider = excluded.provider,
                    model = excluded.model,
                    base_url = excluded.base_url,
                    state = excluded.state,
                    checked_at = excluded.checked_at,
                    status_code = excluded.status_code,
                    model_available = excluded.model_available,
                    error_text = excluded.error_text
                """,
                (
                    key,
                    provider,
                    model,
                    base_url,
                    str(safe.get("state") or "unverified"),
                    int(safe.get("checked_at") or 0),
                    safe.get("status_code"),
                    None if safe.get("model_available") is None else int(bool(safe.get("model_available"))),
                    str(safe.get("error") or "")[:500],
                ),
            )
    except Exception:
        pass


def _llm_verification_is_fresh(result: dict[str, Any]) -> bool:
    checked_at = int(result.get("checked_at") or 0)
    return checked_at > 0 and int(time.time()) - checked_at <= LLM_VERIFICATION_TTL_SECONDS


def _mark_llm_verified(task: str, llm_config: dict[str, Any]) -> None:
    provider = str(llm_config.get("provider", "ollama")).lower()
    model = str(llm_config.get("model") or "").strip()
    base_url = str(llm_config.get("base_url") or "").rstrip("/")
    api_key_env = str(llm_config.get("api_key_env") or _default_api_key_env(provider) or "")
    _store_llm_verification(llm_config, provider, model, base_url, api_key_env, {
        "ok": True,
        "state": "verified",
        "provider": provider,
        "model": model,
        "checked_at": int(time.time()),
        "status_code": None,
        "model_available": True,
        "error": None,
    })


def _default_api_key_env(provider: str) -> str:
    return {
        "openai": "OPENAI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "kimi": "MOONSHOT_API_KEY",
        "moonshot": "MOONSHOT_API_KEY",
    }.get(provider, "")


def _llm_config_for_task(task: str) -> dict[str, Any]:
    config = load_config()
    base = dict(config.get("llm", {}) or {})
    routes = config.get("llm_routes", {}) or {}
    route = routes.get(task) or routes.get("default") or {}
    if isinstance(route, dict):
        base.update(route)
    return base


def _call_compatible_provider(messages: List[Message], llm_config: dict) -> str:
    provider_name = str(llm_config.get("provider_name") or llm_config.get("provider") or "openai_compatible")
    api_key_env = str(llm_config.get("api_key_env") or "")
    if not api_key_env:
        raise RuntimeError("api_key_env is required for openai-compatible LLM providers")
    return _call_chat_completions(
        messages,
        llm_config,
        provider_name=provider_name,
        env_key=api_key_env,
        default_base_url=str(llm_config.get("base_url") or ""),
        default_model=str(llm_config.get("model") or ""),
    )


def _record_llm_call(
    *,
    task: str,
    provider: str,
    model: str,
    status: str,
    prompt_chars: int,
    response_chars: int,
    duration_ms: int,
    error_text: str = "",
) -> None:
    try:
        with get_db() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS llm_call_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task TEXT NOT NULL DEFAULT 'default',
                    provider TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    prompt_chars INTEGER NOT NULL DEFAULT 0,
                    response_chars INTEGER NOT NULL DEFAULT 0,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    error_text TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL
                )
                """
            )
            db.execute(
                """
                INSERT INTO llm_call_logs (
                    task, provider, model, status, prompt_chars, response_chars,
                    duration_ms, error_text, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task or "default",
                    provider,
                    model,
                    status,
                    int(prompt_chars),
                    int(response_chars),
                    int(duration_ms),
                    error_text[:2000],
                    now_ts(),
                ),
            )
    except Exception as exc:
        print("[LLMLog] write failed:", exc)


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
