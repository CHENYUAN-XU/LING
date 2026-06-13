from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.rate_limit import InMemoryRateLimiter, RateLimitRule, first_matching_rule


def main() -> None:
    rule = RateLimitRule(
        name="test_chat",
        methods=frozenset({"POST"}),
        path_prefixes=("/api/chat",),
        limit=2,
        window_seconds=10,
    )
    limiter = InMemoryRateLimiter([rule])

    assert first_matching_rule([rule], "POST", "/api/chat") == rule
    assert first_matching_rule([rule], "GET", "/api/chat") is None
    assert first_matching_rule([rule], "POST", "/api/profile") is None

    assert limiter.check(client_id="ip-a", method="POST", path="/api/chat", now=0)["allowed"] is True
    second = limiter.check(client_id="ip-a", method="POST", path="/api/chat", now=1)
    assert second["allowed"] is True
    assert second["remaining"] == 0
    blocked = limiter.check(client_id="ip-a", method="POST", path="/api/chat", now=2)
    assert blocked["allowed"] is False
    assert blocked["rule"] == "test_chat"
    assert blocked["retry_after"] > 0

    assert limiter.check(client_id="ip-b", method="POST", path="/api/chat", now=2)["allowed"] is True
    assert limiter.check(client_id="ip-a", method="POST", path="/api/chat", now=11)["allowed"] is True
    assert limiter.check(client_id="ip-a", method="GET", path="/api/chat", now=2)["allowed"] is True

    disabled = InMemoryRateLimiter([rule], enabled=False)
    for idx in range(5):
        assert disabled.check(client_id="ip-c", method="POST", path="/api/chat", now=idx)["allowed"] is True

    print("Rate limit verification passed")


if __name__ == "__main__":
    main()
