from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app.database as database


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        database.DB_PATH = Path(tmp) / "middleware.db"
        database.init_db()

        import app.server as server

        client = TestClient(server.app)
        health = client.get("/api/health", headers={"x-request-id": "verify-request-id"})
        assert health.status_code == 200
        assert health.headers["x-request-id"] == "verify-request-id"

        seen_429 = False
        for _ in range(20):
            response = client.post("/api/auth/login", json={"username": "missing-user", "password": "password123"})
            if response.status_code == 429:
                seen_429 = True
                assert response.json()["detail"] == "rate limit exceeded"
                assert "Retry-After" in response.headers
                break
        assert seen_429

    print("Runtime middleware verification passed")


if __name__ == "__main__":
    main()
