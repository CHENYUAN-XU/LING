from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.deployment_check import deployment_report


def main() -> None:
    os.environ["MNEMOSYNE_TEST_DEPLOY_KEY"] = "present"
    good_config = {
        "llm": {"api_key_env": "MNEMOSYNE_TEST_DEPLOY_KEY"},
        "rate_limit": {"enabled": True},
        "logging": {"enabled": True, "request_log_enabled": True},
        "security": {"secure_cookies": True},
        "video_companion": {"enabled": False},
        "proactive": {"scheduler_enabled": False},
    }
    good_report = deployment_report(good_config, production=True)
    assert good_report["ok"] is True
    assert good_report["summary"]["failed"] == 0
    passed_names = {check["name"] for check in good_report["checks"] if check["status"] == "pass"}
    assert {"data_writable", "uploads_writable", "backups_writable"} <= passed_names

    bad_config = {
        "llm": {"api_key_env": "MNEMOSYNE_MISSING_DEPLOY_KEY"},
        "llm_routes": {"chat": {"api_key_env": "MNEMOSYNE_MISSING_DEPLOY_KEY"}},
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

    print("Deployment check verification passed")


if __name__ == "__main__":
    main()
