from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.acceptance_check import acceptance_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect LING daily-use acceptance without external API calls.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--no-port-probe", action="store_true", help="Do not probe configured localhost ports.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero while required checks remain pending/manual.")
    args = parser.parse_args()

    report = acceptance_report(probe_local_ports=not args.no_port_probe)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("LING daily-use acceptance (read-only; no external API calls)")
        for check in report["checks"]:
            requirement = "required" if check["required"] else "optional"
            print(f"- [{check['status'].upper()}] {check['key']} ({requirement}): {check['detail']}")
        summary = report["summary"]
        print(
            "Summary: "
            f"{summary['ready']} ready, {summary['pending']} pending, "
            f"{summary['manual']} manual, {summary['optional']} optional"
        )
        print(f"Automated prerequisites ready: {report['automated_ready']}")
        print(f"Fully accepted on real hardware: {report['fully_accepted']}")
        manual = report.get("manual_acceptance") or {}
        if manual.get("accepted"):
            print("Current manual receipts: " + ", ".join(manual["accepted"]))
        if manual.get("stale"):
            print("Stale manual receipts: " + ", ".join(manual["stale"]))

    if args.strict and not report["fully_accepted"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
