from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.acceptance_check import acceptance_report
from app.manual_acceptance import (
    RECORDABLE_CHECKS,
    load_manual_acceptance,
    record_manual_acceptance,
    revoke_manual_acceptance,
)


LEDGER_PATH = PROJECT_ROOT / "data" / "acceptance" / "manual_acceptance.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Record explicit real-device acceptance evidence for local LING.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    accept = subparsers.add_parser("accept", help="Accept one check after completing its real test.")
    accept.add_argument("check", choices=sorted(RECORDABLE_CHECKS))
    accept.add_argument("--note", required=True, help="Short description of the real test performed.")

    revoke = subparsers.add_parser("revoke", help="Remove one prior manual acceptance receipt.")
    revoke.add_argument("check", choices=sorted(RECORDABLE_CHECKS))

    subparsers.add_parser("list", help="Print the local acceptance ledger.")
    args = parser.parse_args()

    if args.command == "list":
        print(json.dumps(load_manual_acceptance(LEDGER_PATH), ensure_ascii=False, indent=2))
        return
    if args.command == "revoke":
        removed = revoke_manual_acceptance(LEDGER_PATH, args.check)
        print(f"{'Revoked' if removed else 'No receipt found for'}: {args.check}")
        return

    report = acceptance_report(apply_manual_receipts=False)
    receipt = record_manual_acceptance(report["checks"], LEDGER_PATH, args.check, args.note)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    print("Recorded locally. Re-run scripts\\check_acceptance.py to verify the current fingerprint.")


if __name__ == "__main__":
    main()
