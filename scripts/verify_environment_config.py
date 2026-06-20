from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import load_config
from app.environment_check import find_secret_like_config_values, inspect_environment


def main() -> None:
    config = load_config()
    report = inspect_environment(config)
    assert "MOONSHOT_API_KEY" in report["required_env"]
    assert "OPENAI_API_KEY" not in report["required_env"]
    assert not find_secret_like_config_values(config, include_values=False)

    sample = {
        "llm": {
            "api_key_env": "SAFE_ENV_NAME",
            "api_key": "sk-this-should-not-be-here",
        },
        "voice": {
            "enabled": False,
            "api_key_env": "VOICE_DISABLED_KEY",
        },
    }
    sample_report = inspect_environment(sample)
    assert "SAFE_ENV_NAME" in sample_report["required_env"]
    assert "VOICE_DISABLED_KEY" not in sample_report["required_env"]
    voice_enabled_report = inspect_environment({**sample, "voice": {"enabled": True, "api_key_env": "VOICE_ENABLED_KEY"}})
    assert "VOICE_ENABLED_KEY" in voice_enabled_report["required_env"]
    findings = find_secret_like_config_values(sample, include_values=False)
    assert findings and findings[0]["path"] == "llm.api_key"

    print("Environment config verification passed")


if __name__ == "__main__":
    main()
