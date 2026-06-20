from __future__ import annotations

import sys
import os
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    import app.llm_client as llm_client
    import app.database as database

    original_load_config = llm_client.load_config
    original_requests_get = llm_client.requests.get
    original_db_path = database.DB_PATH
    temp_dir = tempfile.TemporaryDirectory()
    try:
        database.DB_PATH = Path(temp_dir.name) / "llm_status.db"
        database.init_db()
        llm_client._LLM_PROBE_CACHE.clear()
        llm_client.load_config = lambda: {
            "llm": {
                "provider": "kimi",
                "model": "kimi-k2.6",
                "base_url": "https://api.moonshot.cn/v1",
                "api_key_env": "MNEMOSYNE_VERIFY_MISSING_KEY",
            },
            "llm_routes": {},
        }
        missing = llm_client.llm_runtime_status("chat")
        assert missing["configured"] is False
        assert missing["verified"] is False
        assert missing["verification"]["state"] == "unverified"
        assert missing["requires_api_key"] is True
        assert missing["missing"] == ["MNEMOSYNE_VERIFY_MISSING_KEY"]
        assert missing["base_url"] == "https://api.moonshot.cn/v1"

        llm_client.load_config = lambda: {
            "llm": {
                "provider": "ollama",
                "model": "qwen2.5:3b",
                "base_url": "http://localhost:11434",
            },
            "llm_routes": {},
        }
        local = llm_client.llm_runtime_status("chat")
        assert local["configured"] is True
        assert local["verified"] is False
        assert local["requires_api_key"] is False
        assert local["missing"] == []
        assert local["base_url"] == "http://localhost:11434"

        calls: list[tuple[str, dict, float]] = []

        class FakeResponse:
            status_code = 200

            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        llm_client.requests.get = lambda url, headers, timeout: (
            calls.append((url, headers, timeout))
            or FakeResponse({"models": [{"name": "qwen2.5:3b"}]})
        )
        local_probe = llm_client.probe_llm_runtime("chat")
        assert local_probe["ok"] is True
        assert local_probe["model_available"] is True
        assert calls[-1][0] == "http://localhost:11434/api/tags"
        verified_local = llm_client.llm_runtime_status("chat")
        assert verified_local["verified"] is True
        assert verified_local["verification"]["state"] == "verified"

        os.environ["MNEMOSYNE_VERIFY_LLM_KEY"] = "test-key"
        llm_client.load_config = lambda: {
            "llm": {
                "provider": "kimi",
                "model": "moonshot-v1-auto",
                "base_url": "https://api.moonshot.cn/v1",
                "api_key_env": "MNEMOSYNE_VERIFY_LLM_KEY",
            },
            "llm_routes": {},
        }
        llm_client.requests.get = lambda url, headers, timeout: (
            calls.append((url, headers, timeout))
            or FakeResponse({"data": [{"id": "moonshot-v1-auto"}]})
        )
        remote_probe = llm_client.probe_llm_runtime("chat")
        assert remote_probe["ok"] is True
        assert calls[-1][0] == "https://api.moonshot.cn/v1/models"
        assert calls[-1][1]["Authorization"] == "Bearer test-key"
        verified_remote = llm_client.llm_runtime_status("chat")
        assert verified_remote["configured"] is True
        assert verified_remote["verified"] is True
        llm_client._LLM_PROBE_CACHE.clear()
        persisted_remote = llm_client.llm_runtime_status("chat")
        assert persisted_remote["verified"] is True
        assert persisted_remote["verification"]["checked_at"] == remote_probe["checked_at"]

        llm_client.load_config = lambda: {
            "llm": {
                "provider": "kimi",
                "model": "missing-model",
                "base_url": "https://api.moonshot.cn/v1",
                "api_key_env": "MNEMOSYNE_VERIFY_LLM_KEY",
            },
            "llm_routes": {},
        }
        missing_model = llm_client.probe_llm_runtime("chat")
        assert missing_model["ok"] is False
        assert missing_model["model_available"] is False
        assert "not available" in missing_model["error"]
    finally:
        llm_client.load_config = original_load_config
        llm_client.requests.get = original_requests_get
        llm_client._LLM_PROBE_CACHE.clear()
        os.environ.pop("MNEMOSYNE_VERIFY_LLM_KEY", None)
        database.DB_PATH = original_db_path
        temp_dir.cleanup()

    print("LLM status verification passed")


if __name__ == "__main__":
    main()
