from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.data_backup import create_data_backup, inspect_data_backup, restore_data_backup


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        db_path = root / "app.db"
        uploads = root / "uploads"
        output = root / "backups"
        restore_dir = root / "restore"
        uploads.mkdir()
        (uploads / "avatars").mkdir()
        (uploads / "avatars" / "one.txt").write_text("avatar-bytes", encoding="utf-8")

        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
            conn.execute("INSERT INTO sample (value) VALUES ('restore-ok')")
            conn.commit()
        finally:
            conn.close()

        result = create_data_backup(
            db_path=db_path,
            uploads_dir=uploads,
            output_dir=output,
            include_uploads=True,
            label="verify restore",
        )
        backup_path = Path(result["backup_path"])

        inspected = inspect_data_backup(backup_path)
        assert inspected["integrity_check"] == "ok"
        assert inspected["uploads_file_count"] == 1
        assert inspected["manifest"]["uploads"]["file_count"] == 1

        restored = restore_data_backup(backup_path, restore_dir)
        restored_db = Path(restored["database_path"])
        restored_upload = restore_dir / "data" / "uploads" / "avatars" / "one.txt"
        assert restored["integrity_check"] == "ok"
        assert restored["uploads_file_count"] == 1
        assert restored_db.exists()
        assert restored_upload.read_text(encoding="utf-8") == "avatar-bytes"
        assert (restore_dir / "manifest.json").exists()

        conn = sqlite3.connect(str(restored_db))
        try:
            row = conn.execute("SELECT value FROM sample WHERE id = 1").fetchone()
            assert row[0] == "restore-ok"
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            conn.close()

        try:
            restore_data_backup(backup_path, restore_dir)
        except FileExistsError:
            pass
        else:
            raise AssertionError("restore should refuse a non-empty target directory")

    print("Backup restore verification passed")


if __name__ == "__main__":
    main()
