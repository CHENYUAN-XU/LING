from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.deployment_check import deployment_report


def main() -> None:
    os.environ["LING_TEST_DEPLOY_KEY"] = "present"
    good_config = {
        "llm": {"api_key_env": "LING_TEST_DEPLOY_KEY"},
        "rate_limit": {"enabled": True},
        "logging": {"enabled": True, "request_log_enabled": True},
        "security": {"secure_cookies": True},
        "voice": {"enabled": False, "api_key_env": "OPENAI_API_KEY"},
        "video_companion": {"enabled": False},
        "proactive": {"scheduler_enabled": False},
    }
    good_report = deployment_report(good_config, production=True)
    assert good_report["ok"] is True
    assert good_report["summary"]["failed"] == 0
    passed_names = {check["name"] for check in good_report["checks"] if check["status"] == "pass"}
    assert {"data_writable", "uploads_writable", "backups_writable"} <= passed_names
    api_key_check = next(check for check in good_report["checks"] if check["name"] == "api_keys")
    assert "OPENAI_API_KEY" not in api_key_check["detail"]

    voice_missing_report = deployment_report(
        {
            "llm": {"api_key_env": "LING_TEST_DEPLOY_KEY"},
            "voice": {"enabled": True, "api_key_env": "LING_MISSING_VOICE_DEPLOY_KEY"},
            "rate_limit": {"enabled": True},
            "logging": {"enabled": True, "request_log_enabled": True},
            "security": {"secure_cookies": True},
            "video_companion": {"enabled": False},
            "proactive": {"scheduler_enabled": False},
        },
        production=True,
    )
    assert voice_missing_report["ok"] is False
    assert any(
        check["name"] == "api_keys" and "LING_MISSING_VOICE_DEPLOY_KEY" in check["detail"]
        for check in voice_missing_report["checks"]
    )

    bad_config = {
        "llm": {"api_key_env": "LING_MISSING_DEPLOY_KEY"},
        "llm_routes": {"chat": {"api_key_env": "LING_MISSING_DEPLOY_KEY"}},
        "rate_limit": {"enabled": False},
        "logging": {"enabled": False, "request_log_enabled": False},
        "security": {"secure_cookies": False},
        "video_companion": {"enabled": True, "project_path": "Z:\\missing-video-companion"},
        "proactive": {"scheduler_enabled": True},
    }
    bad_report = deployment_report(bad_config, production=True)
    failed_names = {check["name"] for check in bad_report["checks"] if check["status"] == "fail"}
    assert bad_report["ok"] is False
    assert {"api_keys", "rate_limit", "request_logging", "secure_cookies", "video_companion_boundary"} <= failed_names
    assert any(check["name"] == "proactive_scheduler" and check["status"] == "warn" for check in bad_report["checks"])

    self_use_report = deployment_report(
        {
            "self_use": {"enabled": True, "require_localhost": True},
            "llm": {"api_key_env": "LING_NOT_CONFIGURED_YET"},
            "rate_limit": {"enabled": True},
            "logging": {"enabled": True, "request_log_enabled": True},
            "security": {"secure_cookies": False},
            "voice": {"enabled": False, "api_key_env": "OPENAI_API_KEY"},
            "video_companion": {"enabled": False},
            "proactive": {"scheduler_enabled": False},
        },
        self_use=True,
    )
    assert self_use_report["ok"] is True
    assert self_use_report["self_use"] is True
    self_use_checks = {check["name"]: check for check in self_use_report["checks"]}
    assert self_use_checks["api_keys"]["status"] == "warn"
    assert self_use_checks["secure_cookies"]["status"] == "pass"
    assert self_use_checks["self_use_boundary"]["status"] == "pass"

    unsafe_self_use = deployment_report(
        {
            "self_use": {"enabled": True, "require_localhost": False},
            "security": {"secure_cookies": True},
            "video_companion": {"enabled": False},
            "proactive": {"scheduler_enabled": False},
        },
        self_use=True,
    )
    unsafe_failed = {check["name"] for check in unsafe_self_use["checks"] if check["status"] == "fail"}
    assert {"secure_cookies", "self_use_boundary"} <= unsafe_failed

    print("Deployment check verification passed")


if __name__ == "__main__":
    main()
