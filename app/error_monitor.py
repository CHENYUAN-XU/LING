from __future__ import annotations

from .database import dict_from_row, get_db, now_ts


def _clean_text(value: object, limit: int) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\r", " ").replace("\n", " ").strip()
    if len(text) > limit:
        if limit <= 3:
            return text[:limit]
        return text[: limit - 3] + "..."
    return text


def record_error_event(
    *,
    request_id: str,
    method: str,
    path: str,
    status_code: int = 500,
    error_type: str = "",
    error_text: str = "",
    client_id: str = "",
) -> dict | None:
    try:
        with get_db() as db:
            event_id = int(
                db.execute(
                    """
                    INSERT INTO app_error_events (
                        request_id, method, path, status_code,
                        error_type, error_text, client_id, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _clean_text(request_id, 120),
                        _clean_text(method, 12).upper(),
                        _clean_text(path, 500),
                        int(status_code),
                        _clean_text(error_type, 120),
                        _clean_text(error_text, 1000),
                        _clean_text(client_id, 120),
                        now_ts(),
                    ),
                ).lastrowid
            )
            row = db.execute("SELECT * FROM app_error_events WHERE id = ?", (event_id,)).fetchone()
            return dict_from_row(row)
    except Exception:
        return None


def list_error_events(limit: int = 50, status_code: int | None = None) -> list[dict]:
    safe_limit = max(1, min(int(limit or 50), 200))
    with get_db() as db:
        if status_code is None:
            rows = db.execute(
                """
                SELECT *
                FROM app_error_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        else:
            rows = db.execute(
                """
                SELECT *
                FROM app_error_events
                WHERE status_code = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(status_code), safe_limit),
            ).fetchall()
    return [dict_from_row(row) for row in rows if row is not None]
