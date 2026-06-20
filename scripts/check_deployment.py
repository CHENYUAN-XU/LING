from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.deployment_check import deployment_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Check deployment readiness.")
    parser.add_argument("--production", action="store_true", help="Treat production blockers as failures.")
    parser.add_argument("--self-use", action="store_true", help="Validate the localhost-only personal LING workspace.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    if args.production and args.self_use:
        parser.error("--production and --self-use are separate deployment modes")
    report = deployment_report(production=args.production, self_use=args.self_use)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("Deployment preflight")
        for check in report["checks"]:
            marker = {"pass": "OK", "warn": "WARN", "fail": "FAIL"}[check["status"]]
            print(f"- [{marker}] {check['name']}: {check['detail']}")
        print(
            f"Summary: {report['summary']['passed']} passed, "
            f"{report['summary']['warnings']} warnings, {report['summary']['failed']} failed"
        )

    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
