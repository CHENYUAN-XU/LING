from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.user_export import export_user_data, write_user_export


def main() -> None:
    parser = argparse.ArgumentParser(description="Export one Project Mnemosyne user's local data as JSON.")
    parser.add_argument("--user-id", type=int, required=True, help="User id to export.")
    parser.add_argument("--uploads", type=Path, default=None, help="Uploads root. Defaults to data/uploads.")
    parser.add_argument("--output", type=Path, default=None, help="Output JSON path. Defaults to stdout.")
    args = parser.parse_args()

    export = export_user_data(args.user_id, uploads_dir=args.uploads)
    if args.output:
        path = write_user_export(args.output, export)
        print(json.dumps({"export_path": str(path), "user_id": args.user_id}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(export, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
