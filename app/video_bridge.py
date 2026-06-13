from __future__ import annotations

import json
from typing import Any

from .conversation_memory import list_conversation_summaries
from .database import dict_from_row, get_db, now_ts
from .layered_memory import recall_layered_memory, summary_prompt
from .user_consent import user_has_consent
from .world_state import store_world_observation


def build_video_session_context(persona_id: int | str | None) -> dict[str, Any]:
    persona = _persona_by_id(persona_id)
    if not persona:
        return _empty_session_context(persona_id)

    user_id = int(persona["user_id"])
    pid = int(persona["id"])
    boundaries = _decode_list(persona.get("boundaries_json"))
    recent_summaries = list_conversation_summaries(user_id, pid, limit=3)
    recent_summary = "\n".join(
        str(item.get("summary_text") or "").strip()
        for item in recent_summaries
        if str(item.get("summary_text") or "").strip()
    )[:2400]
    memory_summary = summary_prompt(user_id, pid)
    layered = recall_layered_memory(user_id, pid, "", limit=10)

    return {
        "persona_id": str(pid),
        "persona_name": str(persona.get("name") or ""),
        "persona_public_info": {
            "summary": persona.get("summary") or "",
            "appearance_description": persona.get("appearance_description") or "",
            "desired_image": persona.get("desired_image") or "",
            "version": int(persona.get("version") or 1),
            "memory_summary": memory_summary,
            "layered_memory": layered,
        },
        "speaking_style": persona.get("speaking_style") or "natural",
        "relationship_status": persona.get("relationship") or "companion",
        "recent_summary": recent_summary,
        "boundaries": boundaries,
        "consent_state": {
            "camera": user_has_consent(user_id, "camera"),
            "microphone": False,
            "external_vision": False,
            "save_summary": True,
            "save_observation": False,
        },
    }


def save_video_session_summary(payload: dict[str, Any], fallback_user_id: int | None = None) -> dict[str, Any]:
    persona = _persona_by_id(payload.get("persona_id"))
    if not persona and fallback_user_id is not None:
        persona = _latest_persona_for_user(fallback_user_id)
    if not persona:
        return {"saved": False, "reason": "persona_not_found"}

    user_id = int(persona["user_id"])
    persona_id = int(persona["id"])
    summary_text = _summary_text(payload)
    if not summary_text:
        return {"saved": False, "reason": "empty_summary"}

    ts = now_ts()
    title = _video_summary_title(payload)
    key_points = _summary_points(payload)
    metadata = {
        "video_companion": True,
        "raw_summary": payload,
    }
    with get_db() as db:
        conversation_id = int(
            db.execute(
                """
                INSERT INTO conversations (user_id, persona_id, title, summary, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, persona_id, title, summary_text[:2000], ts, ts),
            ).lastrowid
        )
        db.execute(
            """
            INSERT INTO messages (conversation_id, user_id, persona_id, role, content, created_at)
            VALUES (?, ?, ?, 'user', ?, ?)
            """,
            (conversation_id, user_id, persona_id, "视频会话结束，保存本次摘要。", ts),
        )
        assistant_message_id = int(
            db.execute(
                """
                INSERT INTO messages (conversation_id, user_id, persona_id, role, content, created_at)
                VALUES (?, ?, ?, 'assistant', ?, ?)
                """,
                (conversation_id, user_id, persona_id, summary_text, ts),
            ).lastrowid
        )
        db.execute(
            """
            INSERT INTO conversation_summaries (
                user_id, persona_id, conversation_id, summary_text, key_points_json,
                covered_message_id, source_message_count, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 2, 'active', ?, ?)
            """,
            (
                user_id,
                persona_id,
                conversation_id,
                summary_text[:6000],
                json.dumps(key_points, ensure_ascii=False),
                assistant_message_id,
                ts,
                ts,
            ),
        )

    observation = store_world_observation(
        user_id=user_id,
        source="video_companion",
        observation_type="session_summary",
        content=summary_text[:2000],
        confidence=0.75,
        metadata=metadata,
    )
    return {
        "saved": True,
        "conversation_id": conversation_id,
        "message_id": assistant_message_id,
        "observation_id": observation.get("id"),
    }


def save_video_observation(payload: dict[str, Any]) -> dict[str, Any]:
    persona = _persona_by_id(payload.get("persona_id"))
    if not persona:
        return {"saved": False, "reason": "persona_required"}
    content = str(
        payload.get("description")
        or payload.get("content")
        or payload.get("presence_status")
        or ""
    ).strip()
    if not content:
        return {"saved": False, "reason": "empty_observation"}

    observation = store_world_observation(
        user_id=int(persona["user_id"]),
        source="video_companion",
        observation_type=str(payload.get("evidence_type") or "video_observation")[:80],
        content=content[:2000],
        confidence=_bounded_float(payload.get("confidence"), default=0.5),
        metadata=payload,
    )
    return {"saved": True, "observation": observation}


def sync_video_consent(payload: dict[str, Any]) -> dict[str, Any]:
    persona = _persona_by_id(payload.get("persona_id"))
    if not persona:
        return {"synced": False, "reason": "persona_required"}
    observation = store_world_observation(
        user_id=int(persona["user_id"]),
        source="video_companion",
        observation_type="consent_sync",
        content="Video Companion consent state synced.",
        confidence=1.0,
        metadata=payload,
    )
    return {"synced": True, "observation_id": observation.get("id")}


def build_video_turn_response(payload: dict[str, Any]) -> dict[str, Any]:
    # The external project remains responsible for low-latency video dialogue.
    # Returning an empty reply keeps the bridge compatible without double-writing chat.
    persona = _persona_by_id(payload.get("persona_id"))
    return {
        "reply_text": "",
        "voice_style": "natural",
        "expression": "neutral",
        "memory_policy": {"should_extract": False, "candidate_only": True},
        "persona_found": bool(persona),
    }


def _persona_by_id(persona_id: int | str | None) -> dict[str, Any] | None:
    try:
        pid = int(str(persona_id or "").strip())
    except (TypeError, ValueError):
        return None
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM personas WHERE id = ? AND status = 'active'",
            (pid,),
        ).fetchone()
    return dict_from_row(row)


def _latest_persona_for_user(user_id: int) -> dict[str, Any] | None:
    with get_db() as db:
        row = db.execute(
            """
            SELECT * FROM personas
            WHERE user_id = ? AND status = 'active'
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
    return dict_from_row(row)


def _empty_session_context(persona_id: int | str | None) -> dict[str, Any]:
    return {
        "persona_id": str(persona_id or ""),
        "persona_name": "",
        "persona_public_info": {},
        "speaking_style": "natural",
        "relationship_status": "companion",
        "recent_summary": "",
        "boundaries": [],
        "consent_state": {
            "camera": False,
            "microphone": False,
            "external_vision": False,
            "save_summary": False,
            "save_observation": False,
        },
    }


def _decode_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    try:
        decoded = json.loads(str(value or "[]"))
    except Exception:
        return []
    if not isinstance(decoded, list):
        return []
    return [str(item).strip() for item in decoded if str(item).strip()]


def _summary_text(payload: dict[str, Any]) -> str:
    candidates = [
        payload.get("summary_text"),
        payload.get("summary"),
        payload.get("history"),
    ]
    nested = payload.get("summary")
    if isinstance(nested, dict):
        candidates.insert(0, nested.get("summary_text"))
    for value in candidates:
        text = str(value or "").strip()
        if text:
            return text[:6000]

    points = _summary_points(payload)
    if points:
        return "\n".join(points)[:6000]
    return ""


def _summary_points(payload: dict[str, Any]) -> list[str]:
    points: list[str] = []
    nested = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    for key in ("key_facts", "memory_candidates", "key_topics", "visual_notes", "system_notes", "risk_flags"):
        for source in (payload, nested):
            value = source.get(key) if isinstance(source, dict) else None
            if isinstance(value, list):
                points.extend(str(item).strip() for item in value if str(item).strip())
            elif isinstance(value, str) and value.strip():
                points.append(value.strip())
    deduped = []
    seen = set()
    for point in points:
        point = " ".join(point.split())[:500]
        if point and point not in seen:
            seen.add(point)
            deduped.append(point)
    return deduped[:50]


def _video_summary_title(payload: dict[str, Any]) -> str:
    nested = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    duration = payload.get("session_duration_sec") or payload.get("duration_sec") or nested.get("duration_sec")
    try:
        minutes = int(float(duration) // 60)
    except (TypeError, ValueError):
        minutes = 0
    return f"视频会话摘要 {minutes}分钟" if minutes else "视频会话摘要"


def _bounded_float(value: Any, default: float = 0.5) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0.0, min(parsed, 1.0))
