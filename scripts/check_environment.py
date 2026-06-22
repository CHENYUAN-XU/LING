from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.environment_check import inspect_environment


def main() -> None:
    parser = argparse.ArgumentParser(description="Check LING environment variable readiness.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when required API key env vars are missing.")
    args = parser.parse_args()

    result = inspect_environment()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["secrets_in_config"]:
        raise SystemExit("config.yaml appears to contain secret-like values")
    if args.strict and result["missing"]:
        raise SystemExit("missing environment variables: " + ", ".join(result["missing"]))


if __name__ == "__main__":
    main()
