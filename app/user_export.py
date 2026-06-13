from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .config import BASE_DIR
from .database import dict_from_row, get_db


DEFAULT_UPLOADS_DIR = BASE_DIR / "data" / "uploads"
EXCLUDED_TABLES = {
    "sessions",
    "memory_counters",
    "expression_asset_settings",
    "llm_call_logs",
}
SENSITIVE_COLUMNS = {"password_hash", "token"}


def export_user_data(user_id: int, *, uploads_dir: Path | str | None = None) -> dict[str, Any]:
    uid = int(user_id)
    uploads_root = Path(uploads_dir) if uploads_dir is not None else DEFAULT_UPLOADS_DIR

    with get_db() as db:
        user = dict_from_row(db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone())
        if not user:
            raise ValueError("user not found")

        refs = {
            "persona_ids": _ids(db, "SELECT id FROM personas WHERE user_id = ?", uid),
            "conversation_ids": _ids(db, "SELECT id FROM conversations WHERE user_id = ?", uid),
            "group_conversation_ids": _ids(db, "SELECT id FROM group_conversations WHERE user_id = ?", uid),
            "message_ids": _ids(db, "SELECT id FROM messages WHERE user_id = ?", uid),
            "group_message_ids": _ids(db, "SELECT id FROM group_messages WHERE user_id = ?", uid),
        }
        tables: dict[str, list[dict[str, Any]]] = {}
        for table in _table_names(db):
            if table in EXCLUDED_TABLES:
                continue
            columns = _columns(db, table)
            selector = _selector_for_table(table, columns, uid, refs)
            if not selector:
                continue
            where_sql, params = selector
            rows = _select_rows(db, table, columns, where_sql, params)
            if rows:
                tables[table] = rows

    upload_files = _uploaded_files_for_user(uploads_root, uid)
    return {
        "export_type": "project_mnemosyne_user_export",
        "created_at": _utc_timestamp(),
        "user_id": uid,
        "tables": tables,
        "uploads": {
            "source_path": str(uploads_root / str(uid)),
            "file_count": len(upload_files),
            "files": upload_files,
        },
        "notes": [
            "Session tokens and password hashes are not included.",
            "Uploaded file contents are not embedded in this JSON export; use the listed paths or a full local backup zip for file bytes.",
        ],
    }


def _selector_for_table(
    table: str,
    columns: list[str],
    user_id: int,
    refs: dict[str, list[int]],
) -> tuple[str, list[Any]] | None:
    if table == "users":
        return "id = ?", [user_id]
    if "user_id" in columns:
        return "user_id = ?", [user_id]
    if "persona_id" in columns:
        return _in_selector("persona_id", refs["persona_ids"])
    if "conversation_id" in columns:
        return _in_selector("conversation_id", refs["conversation_ids"])
    if "group_conversation_id" in columns:
        return _in_selector("group_conversation_id", refs["group_conversation_ids"])
    if "message_id" in columns:
        return _in_selector("message_id", refs["message_ids"])
    if "group_message_id" in columns:
        return _in_selector("group_message_id", refs["group_message_ids"])
    return None


def _in_selector(column: str, values: list[int]) -> tuple[str, list[Any]] | None:
    if not values:
        return None
    placeholders = ",".join("?" for _ in values)
    return f"{column} IN ({placeholders})", list(values)


def _select_rows(db, table: str, columns: list[str], where_sql: str, params: list[Any]) -> list[dict[str, Any]]:
    order_by = " ORDER BY id" if "id" in columns else ""
    rows = db.execute(f"SELECT * FROM {table} WHERE {where_sql}{order_by}", params).fetchall()
    return [_sanitize_row(dict_from_row(row) or {}) for row in rows]


def _sanitize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in SENSITIVE_COLUMNS}


def _table_names(db) -> list[str]:
    rows = db.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    return [str(row["name"]) for row in rows]


def _columns(db, table: str) -> list[str]:
    return [str(row["name"]) for row in db.execute(f"PRAGMA table_info({table})").fetchall()]


def _ids(db, query: str, user_id: int) -> list[int]:
    return [int(row[0]) for row in db.execute(query, (user_id,)).fetchall()]


def _uploaded_files_for_user(uploads_root: Path, user_id: int) -> list[dict[str, Any]]:
    user_dir = uploads_root / str(user_id)
    if not user_dir.exists():
        return []
    if not user_dir.is_dir():
        return []
    files = []
    for path in sorted(user_dir.rglob("*")):
        if not path.is_file():
            continue
        files.append({
            "relative_path": path.relative_to(uploads_root).as_posix(),
            "size_bytes": path.stat().st_size,
        })
    return files


def write_user_export(path: Path | str, export: dict[str, Any]) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(export, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def _utc_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
