from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    import app.llm_client as llm_client

    original_load_config = llm_client.load_config
    try:
        llm_client.load_config = lambda: {
            "llm": {
                "provider": "kimi",
                "model": "kimi-k2.6",
                "api_key_env": "MNEMOSYNE_VERIFY_MISSING_KEY",
            },
            "llm_routes": {},
        }
        missing = llm_client.llm_runtime_status("chat")
        assert missing["configured"] is False
        assert missing["requires_api_key"] is True
        assert missing["missing"] == ["MNEMOSYNE_VERIFY_MISSING_KEY"]

        llm_client.load_config = lambda: {
            "llm": {
                "provider": "ollama",
                "model": "qwen2.5:3b",
            },
            "llm_routes": {},
        }
        local = llm_client.llm_runtime_status("chat")
        assert local["configured"] is True
        assert local["requires_api_key"] is False
        assert local["missing"] == []
    finally:
        llm_client.load_config = original_load_config

    print("LLM status verification passed")


if __name__ == "__main__":
    main()
