from __future__ import annotations

from .database import get_db, now_ts


CONSENT_KEYS = {
    "camera": "摄像头感知",
    "screen": "屏幕感知",
    "proactive": "主动消息",
}


def get_user_consent(user_id: int, consent_key: str) -> dict:
    """Get user consent status for a specific feature."""
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM user_consents WHERE user_id = ? AND consent_key = ?",
            (user_id, consent_key),
        ).fetchone()
    if row:
        return {
            "consent_key": consent_key,
            "label": CONSENT_KEYS.get(consent_key, ""),
            "granted": bool(int(row["granted"] or 0)),
            "granted_at": int(row["granted_at"] or 0),
            "revoked_at": int(row["revoked_at"] or 0),
            "updated_at": int(row["updated_at"] or 0),
        }
    return {
        "consent_key": consent_key,
        "label": CONSENT_KEYS.get(consent_key, ""),
        "granted": False,
        "granted_at": 0,
        "revoked_at": 0,
        "updated_at": 0,
    }


def user_has_consent(user_id: int, consent_key: str) -> bool:
    consent = get_user_consent(user_id, consent_key)
    return consent["granted"]


def grant_consent(user_id: int, consent_key: str) -> dict:
    ts = now_ts()
    with get_db() as db:
        db.execute(
            """
            INSERT INTO user_consents (user_id, consent_key, granted, granted_at, updated_at)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(user_id, consent_key) DO UPDATE SET
                granted = 1, granted_at = ?, revoked_at = 0, updated_at = ?
            """,
            (user_id, consent_key, ts, ts, ts, ts),
        )
    return get_user_consent(user_id, consent_key)


def revoke_consent(user_id: int, consent_key: str) -> dict:
    ts = now_ts()
    with get_db() as db:
        db.execute(
            """
            INSERT INTO user_consents (user_id, consent_key, granted, revoked_at, updated_at)
            VALUES (?, ?, 0, ?, ?)
            ON CONFLICT(user_id, consent_key) DO UPDATE SET
                granted = 0, revoked_at = ?, updated_at = ?
            """,
            (user_id, consent_key, ts, ts, ts, ts),
        )
    return get_user_consent(user_id, consent_key)


def get_all_consents(user_id: int) -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM user_consents WHERE user_id = ? ORDER BY consent_key",
            (user_id,),
        ).fetchall()
    from .database import dict_from_row

    results = []
    seen = set()
    for row in rows:
        result = dict_from_row(row)
        if result:
            key = str(result.get("consent_key") or "")
            result["label"] = CONSENT_KEYS.get(key, "")
            result["granted"] = bool(int(result.get("granted", 0)))
            seen.add(key)
            results.append(result)

    for key, label in sorted(CONSENT_KEYS.items()):
        if key not in seen:
            results.append({
                "consent_key": key,
                "label": label,
                "granted": False,
                "granted_at": 0,
                "revoked_at": 0,
                "updated_at": 0,
            })

    return results
