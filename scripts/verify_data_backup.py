from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.data_backup import create_data_backup


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        db_path = root / "app.db"
        uploads = root / "uploads"
        output = root / "backups"
        uploads.mkdir()
        (uploads / "avatar.txt").write_text("avatar-bytes", encoding="utf-8")

        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
            conn.execute("INSERT INTO sample (value) VALUES ('backup-ok')")
            conn.commit()
        finally:
            conn.close()

        result = create_data_backup(
            db_path=db_path,
            uploads_dir=uploads,
            output_dir=output,
            include_uploads=True,
            label="verify backup",
        )
        backup_path = Path(result["backup_path"])
        assert backup_path.exists()
        assert backup_path.parent == output
        assert result["integrity_check"] == "ok"
        assert result["uploads_file_count"] == 1

        extract_dir = root / "extract"
        with zipfile.ZipFile(backup_path) as archive:
            names = set(archive.namelist())
            assert "manifest.json" in names
            assert "database/app.db" in names
            assert "uploads/avatar.txt" in names
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            assert manifest["database"]["integrity_check"] == "ok"
            assert manifest["uploads"]["file_count"] == 1
            archive.extract("database/app.db", extract_dir)

        restored_db = extract_dir / "database" / "app.db"
        conn = sqlite3.connect(str(restored_db))
        try:
            row = conn.execute("SELECT value FROM sample WHERE id = 1").fetchone()
            assert row[0] == "backup-ok"
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            conn.close()

    print("Data backup verification passed")


if __name__ == "__main__":
    main()
