from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.data_backup import inspect_data_backup, restore_data_backup


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect or restore a Project Mnemosyne data backup.")
    parser.add_argument("backup", type=Path, help="Backup zip path.")
    parser.add_argument(
        "--restore-dir",
        type=Path,
        default=None,
        help="Empty directory to restore into. Required unless --inspect-only is used.",
    )
    parser.add_argument("--inspect-only", action="store_true", help="Only inspect the backup zip.")
    args = parser.parse_args()

    if args.inspect_only:
        result = inspect_data_backup(args.backup)
    else:
        if args.restore_dir is None:
            raise SystemExit("--restore-dir is required unless --inspect-only is used")
        result = restore_data_backup(args.backup, args.restore_dir)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
