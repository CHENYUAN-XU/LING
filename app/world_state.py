from __future__ import annotations

import json
from typing import Any

from .config import load_config
from .database import get_db, now_ts


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _bounded_confidence(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 0.5
    return max(0.0, min(parsed, 1.0))


def store_world_observation(
    user_id: int,
    source: str,
    observation_type: str,
    content: str,
    confidence: float = 0.5,
    metadata: dict | None = None,
) -> dict:
    """Store a world observation. Does NOT write to long-term memory."""
    ts = now_ts()
    safe_confidence = _bounded_confidence(confidence)
    with get_db() as db:
        cursor = db.execute(
            """
            INSERT INTO world_observations (
                user_id, source, observation_type, content, confidence,
                metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                source,
                observation_type,
                content,
                safe_confidence,
                json.dumps(metadata or {}, ensure_ascii=False),
                ts,
            ),
        )
        observation_id = int(cursor.lastrowid)
        row = db.execute(
            "SELECT * FROM world_observations WHERE id = ?",
            (observation_id,),
        ).fetchone()

    from .database import dict_from_row
    return dict_from_row(row) or {}


def get_recent_world_observations(
    user_id: int,
    source: str | None = None,
    observation_type: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Get recent world observations. Does NOT modify long-term memory."""
    params: list[Any] = [user_id]
    clauses = ["user_id = ?"]

    if source:
        clauses.append("source = ?")
        params.append(source)
    if observation_type:
        clauses.append("observation_type = ?")
        params.append(observation_type)

    where = " AND ".join(clauses)
    params.append(_bounded_int(limit, default=20, minimum=1, maximum=100))

    with get_db() as db:
        rows = db.execute(
            f"""
            SELECT id, user_id, source, observation_type, content, confidence,
                   metadata_json, created_at
            FROM world_observations
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    from .database import dict_from_row
    return [dict_from_row(row) for row in rows]


def get_world_state_summary(user_id: int) -> dict:
    """Get a summary of current world state. Separate from memory state."""
    observations = get_recent_world_observations(user_id, limit=50)

    sources: dict[str, list[dict]] = {}
    for obs in observations:
        src = str(obs.get("source") or "unknown")
        sources.setdefault(src, []).append(obs)

    recent_presence = [
        obs for obs in observations
        if obs.get("observation_type") in ("user_presence", "user_leave", "user_return")
    ][:5]

    return {
        "total_observations": len(observations),
        "sources": {src: len(items) for src, items in sources.items()},
        "recent_presence_events": recent_presence,
        "latest_observation": observations[0] if observations else None,
    }
