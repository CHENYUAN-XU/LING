from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.data_backup import create_data_backup


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a local LING data backup.")
    parser.add_argument("--db", type=Path, default=None, help="SQLite database path. Defaults to data/app.db.")
    parser.add_argument("--uploads", type=Path, default=None, help="Uploads directory. Defaults to data/uploads.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Backup output directory. Defaults to data/backups.")
    parser.add_argument("--label", default="", help="Optional safe label included in the backup filename.")
    parser.add_argument("--no-uploads", action="store_true", help="Only include the SQLite database snapshot.")
    args = parser.parse_args()

    result = create_data_backup(
        db_path=args.db,
        uploads_dir=args.uploads,
        output_dir=args.output_dir,
        include_uploads=not args.no_uploads,
        label=args.label,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
