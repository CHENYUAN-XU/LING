from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run(label: str, command: list[str]) -> None:
    print(f"\n== {label} ==", flush=True)
    print(" ".join(command), flush=True)
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the LING verification suite.")
    parser.add_argument(
        "--http-smoke",
        metavar="BASE_URL",
        help="Also verify a running server, for example http://127.0.0.1:8001.",
    )
    parser.add_argument(
        "--video-e2e",
        action="store_true",
        help="Also start LING and Video Companion on temporary ports and verify the bridge.",
    )
    args = parser.parse_args()

    py = sys.executable
    node = shutil.which("node")
    if not node:
        raise SystemExit("node is required for JavaScript syntax checks")

    run("Python compile", [py, "-m", "compileall", "app", "scripts"])
    run("Web app syntax", [node, "--check", "web\\app.js"])
    run("Admin app syntax", [node, "--check", "admin_web\\admin.js"])

    for script in (
        "scripts\\verify_pwa_assets.py",
        "scripts\\verify_ling_shell.py",
        "scripts\\verify_companion_status.py",
        "scripts\\verify_profile_timezone.py",
        "scripts\\verify_phase1_flows.py",
        "scripts\\verify_phase2_growth.py",
        "scripts\\verify_phase3_expression.py",
        "scripts\\verify_phase4_voice.py",
        "scripts\\verify_phase5_live2d.py",
        "scripts\\verify_phase6_presence.py",
        "scripts\\verify_phase7_camera.py",
        "scripts\\verify_phase8_screen.py",
        "scripts\\verify_phase9_proactive.py",
        "scripts\\verify_llm_status.py",
        "scripts\\verify_embodiment_fields.py",
        "scripts\\verify_video_companion_adapter.py",
        "scripts\\verify_data_backup.py",
        "scripts\\verify_backup_restore.py",
        "scripts\\verify_avatar_upload.py",
        "scripts\\verify_avatar_url.py",
        "scripts\\verify_user_export.py",
        "scripts\\verify_rate_limit.py",
        "scripts\\verify_request_logging.py",
        "scripts\\verify_error_monitor.py",
        "scripts\\verify_admin_error_events_ui.py",
        "scripts\\verify_privacy_policy.py",
        "scripts\\verify_deployment_check.py",
        "scripts\\verify_sqlite_runtime.py",
        "scripts\\verify_guest_admin.py",
        "scripts\\verify_self_use_login.py",
        "scripts\\verify_ling_prompt.py",
        "scripts\\verify_acceptance_check.py",
        "scripts\\verify_self_use_chat_gate.py",
        "scripts\\verify_self_use_soak.py",
        "scripts\\verify_local_launcher.py",
        "scripts\\verify_persona_purge.py",
        "scripts\\verify_account_delete.py",
        "scripts\\verify_admin_protection.py",
        "scripts\\verify_environment_config.py",
        "scripts\\verify_runtime_middleware.py",
        "scripts\\verify_group_chat.py",
    ):
        run(script, [py, script])

    if args.http_smoke:
        run("HTTP smoke", [py, "scripts\\verify_http_smoke.py", args.http_smoke])

    if args.video_e2e:
        run("Video Companion E2E", [py, "scripts\\verify_video_companion_e2e.py"])

    print("\nAll verification checks passed.", flush=True)


if __name__ == "__main__":
    main()
