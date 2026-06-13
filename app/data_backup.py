from __future__ import annotations

import json
import re
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from .config import BASE_DIR
from .database import DB_PATH


DEFAULT_BACKUP_DIR = BASE_DIR / "data" / "backups"
DEFAULT_UPLOADS_DIR = BASE_DIR / "data" / "uploads"


def create_data_backup(
    *,
    db_path: Path | str | None = None,
    uploads_dir: Path | str | None = None,
    output_dir: Path | str | None = None,
    include_uploads: bool = True,
    label: str = "",
) -> dict[str, Any]:
    source_db = Path(db_path) if db_path is not None else DB_PATH
    source_uploads = Path(uploads_dir) if uploads_dir is not None else DEFAULT_UPLOADS_DIR
    backups_dir = Path(output_dir) if output_dir is not None else DEFAULT_BACKUP_DIR

    if not source_db.exists():
        raise FileNotFoundError(f"database not found: {source_db}")
    if not source_db.is_file():
        raise ValueError(f"database path is not a file: {source_db}")

    backups_dir.mkdir(parents=True, exist_ok=True)
    backup_name = _backup_filename(label)
    backup_path = backups_dir / backup_name
    if backup_path.exists():
        backup_path = backups_dir / f"{backup_path.stem}-{int(time.time() * 1000)}.zip"

    with tempfile.TemporaryDirectory(prefix="mnemosyne-backup-", dir=str(backups_dir)) as tmp:
        tmp_path = Path(tmp)
        snapshot_db = tmp_path / "app.db"
        _snapshot_sqlite(source_db, snapshot_db)
        integrity = _sqlite_integrity_check(snapshot_db)
        if integrity != "ok":
            raise RuntimeError(f"backup integrity check failed: {integrity}")

        upload_files = _iter_upload_files(source_uploads) if include_uploads else []
        manifest = {
            "project": "Project Mnemosyne",
            "created_at": _utc_timestamp(),
            "database": {
                "source_path": str(source_db),
                "archive_path": "database/app.db",
                "integrity_check": integrity,
                "size_bytes": snapshot_db.stat().st_size,
            },
            "uploads": {
                "included": bool(include_uploads),
                "source_path": str(source_uploads),
                "file_count": len(upload_files),
            },
        }

        with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            archive.write(snapshot_db, "database/app.db")
            for file_path in upload_files:
                archive.write(file_path, "uploads/" + file_path.relative_to(source_uploads).as_posix())

    return {
        "backup_path": str(backup_path),
        "database_path": str(source_db),
        "uploads_path": str(source_uploads),
        "include_uploads": bool(include_uploads),
        "uploads_file_count": manifest["uploads"]["file_count"],
        "integrity_check": manifest["database"]["integrity_check"],
        "size_bytes": backup_path.stat().st_size,
    }


def _snapshot_sqlite(source_db: Path, snapshot_db: Path) -> None:
    source = sqlite3.connect(str(source_db))
    target = sqlite3.connect(str(snapshot_db))
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def _sqlite_integrity_check(db_path: Path) -> str:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        return str(row[0] if row else "")
    finally:
        conn.close()


def _iter_upload_files(uploads_dir: Path) -> list[Path]:
    if not uploads_dir.exists():
        return []
    if not uploads_dir.is_dir():
        raise ValueError(f"uploads path is not a directory: {uploads_dir}")
    return sorted(path for path in uploads_dir.rglob("*") if path.is_file())


def _backup_filename(label: str = "") -> str:
    suffix = _safe_label(label)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    return f"mnemosyne-backup-{stamp}{('-' + suffix) if suffix else ''}.zip"


def _safe_label(label: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(label or "").strip()).strip(".-_")
    return cleaned[:48]


def _utc_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
