from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from fastapi import Request

from .config import load_config


DEFAULT_RULES = [
    {"name": "auth", "methods": ["POST"], "path_prefixes": ["/api/auth/"], "limit": 12, "window_seconds": 60},
    {"name": "chat", "methods": ["POST"], "path_prefixes": ["/api/chat", "/api/group-chat"], "limit": 45, "window_seconds": 60},
    {"name": "uploads", "methods": ["POST"], "path_prefixes": ["/api/uploads/"], "limit": 20, "window_seconds": 60},
    {"name": "account_export", "methods": ["GET"], "path_prefixes": ["/api/account/export"], "limit": 10, "window_seconds": 600},
    {"name": "persona_write", "methods": ["POST", "PATCH", "DELETE"], "path_prefixes": ["/api/personas"], "limit": 60, "window_seconds": 60},
]


@dataclass(frozen=True)
class RateLimitRule:
    name: str
    methods: frozenset[str]
    path_prefixes: tuple[str, ...]
    limit: int
    window_seconds: int

    def matches(self, method: str, path: str) -> bool:
        return method.upper() in self.methods and any(path.startswith(prefix) for prefix in self.path_prefixes)


class InMemoryRateLimiter:
    def __init__(self, rules: list[RateLimitRule] | None = None, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self.rules = rules or load_rate_limit_rules()
        self._buckets: dict[tuple[str, str], tuple[float, int]] = {}
        self._lock = threading.Lock()

    def check(self, *, client_id: str, method: str, path: str, now: float | None = None) -> dict[str, Any]:
        if not self.enabled:
            return {"allowed": True}
        rule = first_matching_rule(self.rules, method, path)
        if not rule:
            return {"allowed": True}

        now = time.monotonic() if now is None else now
        key = (rule.name, client_id)
        with self._lock:
            window_start, count = self._buckets.get(key, (now, 0))
            if now - window_start >= rule.window_seconds:
                window_start = now
                count = 0
            count += 1
            self._buckets[key] = (window_start, count)
            self._cleanup(now)

        reset_after = max(0, int(rule.window_seconds - (now - window_start)))
        return {
            "allowed": count <= rule.limit,
            "rule": rule.name,
            "limit": rule.limit,
            "remaining": max(0, rule.limit - count),
            "retry_after": reset_after or rule.window_seconds,
        }

    def _cleanup(self, now: float) -> None:
        stale = [
            key
            for key, (window_start, _) in self._buckets.items()
            if now - window_start > 3600
        ]
        for key in stale:
            self._buckets.pop(key, None)


def load_rate_limit_rules() -> list[RateLimitRule]:
    raw = load_config().get("rate_limit", {})
    rules = raw.get("rules") if isinstance(raw, dict) else None
    if not isinstance(rules, list):
        rules = DEFAULT_RULES
    parsed: list[RateLimitRule] = []
    for item in rules:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        methods = item.get("methods") or []
        prefixes = item.get("path_prefixes") or []
        try:
            limit = int(item.get("limit", 0))
            window_seconds = int(item.get("window_seconds", 0))
        except (TypeError, ValueError):
            continue
        if not name or limit <= 0 or window_seconds <= 0:
            continue
        parsed.append(RateLimitRule(
            name=name,
            methods=frozenset(str(method).upper() for method in methods),
            path_prefixes=tuple(str(prefix) for prefix in prefixes if str(prefix)),
            limit=limit,
            window_seconds=window_seconds,
        ))
    return parsed or [RateLimitRule(
        name=str(item["name"]),
        methods=frozenset(str(method).upper() for method in item["methods"]),
        path_prefixes=tuple(str(prefix) for prefix in item["path_prefixes"]),
        limit=int(item["limit"]),
        window_seconds=int(item["window_seconds"]),
    ) for item in DEFAULT_RULES]


def rate_limit_enabled() -> bool:
    raw = load_config().get("rate_limit", {})
    if not isinstance(raw, dict):
        return True
    return bool(raw.get("enabled", True))


def first_matching_rule(rules: list[RateLimitRule], method: str, path: str) -> RateLimitRule | None:
    for rule in rules:
        if rule.matches(method, path):
            return rule
    return None


def client_identifier(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    if forwarded:
        return forwarded
    if request.client and request.client.host:
        return request.client.host
    return "unknown"
