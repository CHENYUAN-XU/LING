from __future__ import annotations

import json
import threading
import time
from typing import Any

from .config import load_config
from .database import get_db, now_ts


DEFAULT_PROACTIVE_CONFIG: dict[str, Any] = {
    "enabled": False,
    "min_interval_seconds": 300,
    "cooldown_after_negative_seconds": 1800,
    "max_per_hour": 3,
    "quiet_mode_enabled": False,
    "user_positive_multiplier": 1.0,
    "user_negative_multiplier": 0.5,
    "min_user_idle_seconds": 900,
    "max_messages_per_tick": 1,
    "max_candidate_personas": 20,
    "scheduler_enabled": False,
    "scheduler_interval_seconds": 300,
}

_scheduler_lock = threading.Lock()
_scheduler_thread: threading.Thread | None = None
_scheduler_stop_event: threading.Event | None = None
_scheduler_last_run_at = 0
_scheduler_last_result: dict[str, Any] | None = None
_scheduler_last_error: str | None = None


def load_proactive_config() -> dict[str, Any]:
    config = load_config()
    proactive_cfg = config.get("proactive", {}) or {}
    if not isinstance(proactive_cfg, dict):
        proactive_cfg = {}
    merged = dict(DEFAULT_PROACTIVE_CONFIG)
    for key, value in proactive_cfg.items():
        if key in merged:
            merged[key] = value
    return merged


def proactive_enabled(user_id: int | None = None) -> bool:
    config_enabled = bool(load_proactive_config().get("enabled", False))
    if not config_enabled:
        return False
    if user_id is not None:
        from .user_consent import user_has_consent
        if not user_has_consent(user_id, "proactive"):
            return False
    return True


def proactive_scheduler_enabled() -> bool:
    config = load_proactive_config()
    return bool(config.get("enabled", False)) and bool(config.get("scheduler_enabled", False))


class ProactiveController:
    """Controls proactive messaging behavior with frequency limiting."""

    def __init__(self, user_id: int, persona_id: int):
        self.user_id = user_id
        self.persona_id = persona_id
        self._config = load_proactive_config()
        self._proactive_state = self._load_state()

    def _load_state(self) -> dict:
        with get_db() as db:
            row = db.execute(
                """
                SELECT * FROM proactive_state
                WHERE user_id = ? AND persona_id = ?
                """,
                (self.user_id, self.persona_id),
            ).fetchone()
        if row:
            return {
                "user_id": self.user_id,
                "persona_id": self.persona_id,
                "last_proactive_at": int(row["last_proactive_at"] or 0),
                "proactive_count_this_hour": int(row["proactive_count_this_hour"] or 0),
                "hour_start_at": int(row["hour_start_at"] or 0),
                "quiet_mode": bool(int(row["quiet_mode"] or 0)),
                "user_positive_count": int(row["user_positive_count"] or 0),
                "user_negative_count": int(row["user_negative_count"] or 0),
                "updated_at": int(row["updated_at"] or 0),
            }
        return {
            "user_id": self.user_id,
            "persona_id": self.persona_id,
            "last_proactive_at": 0,
            "proactive_count_this_hour": 0,
            "hour_start_at": 0,
            "quiet_mode": False,
            "user_positive_count": 0,
            "user_negative_count": 0,
            "updated_at": 0,
        }

    def _save_state(self) -> None:
        ts = now_ts()
        with get_db() as db:
            db.execute(
                """
                INSERT INTO proactive_state (
                    user_id, persona_id, last_proactive_at, proactive_count_this_hour,
                    hour_start_at, quiet_mode, user_positive_count, user_negative_count, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, persona_id) DO UPDATE SET
                    last_proactive_at = excluded.last_proactive_at,
                    proactive_count_this_hour = excluded.proactive_count_this_hour,
                    hour_start_at = excluded.hour_start_at,
                    quiet_mode = excluded.quiet_mode,
                    user_positive_count = excluded.user_positive_count,
                    user_negative_count = excluded.user_negative_count,
                    updated_at = excluded.updated_at
                """,
                (
                    self.user_id,
                    self.persona_id,
                    self._proactive_state["last_proactive_at"],
                    self._proactive_state["proactive_count_this_hour"],
                    self._proactive_state["hour_start_at"],
                    1 if self._proactive_state["quiet_mode"] else 0,
                    self._proactive_state["user_positive_count"],
                    self._proactive_state["user_negative_count"],
                    ts,
                ),
            )

    @property
    def is_quiet(self) -> bool:
        return self._proactive_state["quiet_mode"]

    def set_quiet_mode(self, quiet: bool) -> None:
        self._proactive_state["quiet_mode"] = quiet
        self._save_state()

    def record_user_feedback(self, positive: bool) -> None:
        if positive:
            self._proactive_state["user_positive_count"] += 1
        else:
            self._proactive_state["user_negative_count"] += 1
        self._save_state()

    def can_send_proactive(self) -> dict[str, Any]:
        """Check whether a proactive message can be sent now."""
        if not proactive_enabled(self.user_id):
            return {"allowed": False, "reason": "proactive_disabled"}

        ownership = self._verify_persona_ownership(self.user_id, self.persona_id)
        if not ownership["valid"]:
            return {"allowed": False, "reason": "persona_not_owned", "detail": ownership}

        if self._proactive_state["quiet_mode"]:
            return {"allowed": False, "reason": "quiet_mode"}

        now = time.time()
        config = load_proactive_config()

        min_interval = int(config.get("min_interval_seconds", 300))
        last_at = self._proactive_state["last_proactive_at"]
        if last_at > 0 and (now - last_at) < min_interval:
            remaining = int(min_interval - (now - last_at))
            return {"allowed": False, "reason": "cooldown", "remaining_seconds": remaining}

        max_per_hour = int(config.get("max_per_hour", 3))
        hour_start = self._proactive_state["hour_start_at"]
        if hour_start > 0 and (now - hour_start) < 3600:
            if self._proactive_state["proactive_count_this_hour"] >= max_per_hour:
                return {"allowed": False, "reason": "hourly_limit"}
        else:
            self._proactive_state["hour_start_at"] = int(now)
            self._proactive_state["proactive_count_this_hour"] = 0

        negative_cooldown = int(config.get("cooldown_after_negative_seconds", 1800))
        negatives = self._proactive_state["user_negative_count"]
        if negatives > 0 and (now - last_at) < negative_cooldown:
            remaining = int(negative_cooldown - (now - last_at))
            return {"allowed": False, "reason": "negative_cooldown", "remaining_seconds": remaining}

        risk = self._assess_pre_send_risk()
        if not risk["safe"]:
            return {"allowed": False, "reason": f"risk_{risk['level']}", "risk_detail": risk}

        return {"allowed": True, "reason": "ready"}

    def _assess_pre_send_risk(self) -> dict[str, Any]:
        """Pre-send risk assessment based on Mirror user preferences and state."""
        positives = self._proactive_state["user_positive_count"]
        negatives = self._proactive_state["user_negative_count"]

        total = positives + negatives
        if total == 0:
            return {"safe": True, "level": "low", "reason": "no_feedback_yet"}

        negative_ratio = negatives / max(total, 1)
        if negative_ratio >= 0.7:
            return {"safe": False, "level": "high", "reason": "mostly_negative_feedback"}
        if negative_ratio >= 0.4:
            return {"safe": False, "level": "medium", "reason": "significant_negative_feedback"}

        return {"safe": True, "level": "low", "reason": "acceptable_feedback_ratio"}

    @staticmethod
    def _verify_persona_ownership(user_id: int, persona_id: int) -> dict:
        from .database import get_db
        with get_db() as db:
            row = db.execute(
                "SELECT id FROM personas WHERE id = ? AND user_id = ? AND status = 'active'",
                (persona_id, user_id),
            ).fetchone()
        if row:
            return {"valid": True}
        return {"valid": False, "reason": "persona does not belong to user or is not active"}

    def on_proactive_sent(self) -> None:
        can_send = self.can_send_proactive()
        if not can_send.get("allowed"):
            raise PermissionError(str(can_send))
        now = int(time.time())
        self._proactive_state["last_proactive_at"] = now
        self._proactive_state["proactive_count_this_hour"] += 1
        self._proactive_state["updated_at"] = now
        self._save_state()

    def get_status(self) -> dict:
        can_send = self.can_send_proactive()
        return {
            "config": load_proactive_config(),
            "state": self._proactive_state,
            "can_send": can_send,
        }


def get_proactive_controller(user_id: int, persona_id: int) -> ProactiveController:
    return ProactiveController(user_id, persona_id)


def run_proactive_tick(
    user_id: int | None = None,
    persona_id: int | None = None,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run one bounded proactive scan.

    This is intentionally a single tick, not a permanent background thread.
    A scheduler can call it later, while tests and the UI can verify it safely.
    """
    if user_id is not None and not proactive_enabled(user_id):
        return {"enabled": False, "sent": 0, "skipped": [{"reason": "proactive_disabled"}]}
    if user_id is None and not proactive_enabled():
        return {"enabled": False, "sent": 0, "skipped": [{"reason": "proactive_disabled"}]}

    config = load_proactive_config()
    max_messages = max(0, int(config.get("max_messages_per_tick", 1) or 1))
    candidates = _proactive_candidates(user_id=user_id, persona_id=persona_id)
    sent: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for candidate in candidates:
        if len(sent) >= max_messages:
            skipped.append({
                "user_id": candidate["user_id"],
                "persona_id": candidate["persona_id"],
                "reason": "tick_limit",
            })
            continue

        result = _maybe_send_proactive_candidate(candidate, dry_run=dry_run)
        if result.get("sent"):
            sent.append(result)
        else:
            skipped.append(result)

    return {
        "enabled": True,
        "dry_run": dry_run,
        "sent": len(sent),
        "messages": sent,
        "skipped": skipped,
        "candidates_checked": len(candidates),
    }


def start_proactive_scheduler() -> dict[str, Any]:
    global _scheduler_thread, _scheduler_stop_event

    if not proactive_scheduler_enabled():
        return get_proactive_scheduler_status(reason="scheduler_disabled")

    already_running = False
    with _scheduler_lock:
        if _scheduler_thread and _scheduler_thread.is_alive():
            already_running = True
        else:
            stop_event = threading.Event()
            thread = threading.Thread(
                target=_proactive_scheduler_loop,
                args=(stop_event,),
                name="ling-proactive-scheduler",
                daemon=True,
            )
            _scheduler_stop_event = stop_event
            _scheduler_thread = thread
            thread.start()

    if already_running:
        return get_proactive_scheduler_status(reason="already_running")
    return get_proactive_scheduler_status(reason="started")


def stop_proactive_scheduler() -> dict[str, Any]:
    global _scheduler_thread, _scheduler_stop_event

    with _scheduler_lock:
        thread = _scheduler_thread
        stop_event = _scheduler_stop_event
        if stop_event:
            stop_event.set()

    if thread and thread.is_alive():
        thread.join(timeout=3)

    with _scheduler_lock:
        if _scheduler_thread is thread:
            _scheduler_thread = None
            _scheduler_stop_event = None

    return get_proactive_scheduler_status(reason="stopped")


def get_proactive_scheduler_status(reason: str | None = None) -> dict[str, Any]:
    config = load_proactive_config()
    with _scheduler_lock:
        running = bool(_scheduler_thread and _scheduler_thread.is_alive())
        return {
            "enabled": bool(config.get("enabled", False)),
            "scheduler_enabled": bool(config.get("scheduler_enabled", False)),
            "running": running,
            "interval_seconds": int(config.get("scheduler_interval_seconds", 300) or 300),
            "last_run_at": _scheduler_last_run_at,
            "last_result": _scheduler_last_result,
            "last_error": _scheduler_last_error,
            "reason": reason,
        }


def _proactive_scheduler_loop(stop_event: threading.Event) -> None:
    global _scheduler_last_error, _scheduler_last_result, _scheduler_last_run_at

    while not stop_event.is_set():
        config = load_proactive_config()
        interval = max(30, int(config.get("scheduler_interval_seconds", 300) or 300))
        if stop_event.wait(interval):
            break
        if not proactive_scheduler_enabled():
            continue
        try:
            result = run_proactive_tick()
            with _scheduler_lock:
                _scheduler_last_run_at = now_ts()
                _scheduler_last_result = result
                _scheduler_last_error = None
        except Exception as exc:
            with _scheduler_lock:
                _scheduler_last_run_at = now_ts()
                _scheduler_last_error = f"{type(exc).__name__}: {exc}"


def _proactive_candidates(user_id: int | None = None, persona_id: int | None = None) -> list[dict[str, Any]]:
    config = load_proactive_config()
    full_config = load_config()
    self_use = full_config.get("self_use", {}) if isinstance(full_config.get("self_use"), dict) else {}
    self_use_enabled = bool(self_use.get("enabled", False))
    limit = max(1, int(config.get("max_candidate_personas", 20) or 20))
    params: list[Any] = []
    filters = ["users.status = 'active'", "personas.status = 'active'"]
    binding_join = ""
    if self_use_enabled:
        binding_join = "JOIN self_use_companion_bindings ON self_use_companion_bindings.user_id = users.id"
        filters.extend([
            "users.username = ?",
            "personas.id = self_use_companion_bindings.persona_id",
        ])
        params.append(str(self_use.get("username") or "mio_owner"))
    if user_id is not None:
        filters.append("users.id = ?")
        params.append(user_id)
    if persona_id is not None:
        filters.append("personas.id = ?")
        params.append(persona_id)
    params.append(limit)

    with get_db() as db:
        rows = db.execute(
            f"""
            SELECT users.id AS user_id,
                   personas.id AS persona_id,
                   personas.name AS persona_name,
                   personas.prompt AS persona_prompt,
                   personas.summary AS persona_summary,
                   personas.relationship AS relationship,
                   personas.speaking_style AS speaking_style,
                   personas.updated_at AS persona_updated_at
            FROM users
            JOIN personas ON personas.user_id = users.id
            {binding_join}
            JOIN user_consents
              ON user_consents.user_id = users.id
             AND user_consents.consent_key = 'proactive'
             AND user_consents.granted = 1
            WHERE {" AND ".join(filters)}
            ORDER BY personas.updated_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    candidates = [dict(row) for row in rows]
    for candidate in candidates:
        candidate["self_use_companion"] = self_use_enabled
    return candidates


def _maybe_send_proactive_candidate(candidate: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    user_id = int(candidate["user_id"])
    persona_id = int(candidate["persona_id"])
    base = {"user_id": user_id, "persona_id": persona_id}

    controller = get_proactive_controller(user_id, persona_id)
    can_send = controller.can_send_proactive()
    if not can_send.get("allowed"):
        return {**base, "sent": False, "reason": can_send.get("reason", "blocked"), "detail": can_send}

    context = _latest_conversation_context(user_id, persona_id)
    if not context:
        return {**base, "sent": False, "reason": "no_conversation"}

    config = load_proactive_config()
    min_idle = int(config.get("min_user_idle_seconds", 900) or 0)
    latest_message = context.get("latest_message") or {}
    latest_at = int(latest_message.get("created_at") or 0)
    idle_seconds = max(0, now_ts() - latest_at) if latest_at else 0
    if latest_at and idle_seconds < min_idle:
        return {
            **base,
            "sent": False,
            "reason": "recent_interaction",
            "idle_seconds": idle_seconds,
            "required_idle_seconds": min_idle,
        }

    if dry_run:
        return {
            **base,
            "sent": False,
            "reason": "dry_run_ready",
            "conversation_id": context["conversation_id"],
            "idle_seconds": idle_seconds,
        }

    try:
        reply_result = _generate_proactive_reply(candidate, context)
    except Exception as exc:
        return {**base, "sent": False, "reason": "generation_failed", "error": str(exc)}

    reply = str(reply_result.get("reply") or "").strip()
    if not reply:
        return {**base, "sent": False, "reason": "empty_reply"}

    can_send_after_generation = controller.can_send_proactive()
    if not can_send_after_generation.get("allowed"):
        return {
            **base,
            "sent": False,
            "reason": can_send_after_generation.get("reason", "blocked_after_generation"),
            "detail": can_send_after_generation,
        }

    ts = now_ts()
    with get_db() as db:
        cursor = db.execute(
            """
            INSERT INTO messages (conversation_id, user_id, persona_id, role, content, created_at)
            VALUES (?, ?, ?, 'assistant', ?, ?)
            """,
            (context["conversation_id"], user_id, persona_id, reply, ts),
        )
        assistant_message_id = int(cursor.lastrowid)
        expressions = reply_result.get("expressions") or []
        if expressions:
            from .db_chat import _store_message_expressions

            _store_message_expressions(
                db,
                message_id=assistant_message_id,
                user_id=user_id,
                persona_id=persona_id,
                conversation_id=int(context["conversation_id"]),
                expressions=expressions,
                created_at=ts,
            )
        db.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (ts, context["conversation_id"]),
        )

    controller.on_proactive_sent()
    return {
        **base,
        "sent": True,
        "conversation_id": context["conversation_id"],
        "assistant_message_id": assistant_message_id,
        "reply": reply,
        "expressions": reply_result.get("expressions") or [],
    }


def _latest_conversation_context(user_id: int, persona_id: int) -> dict[str, Any] | None:
    with get_db() as db:
        conversation = db.execute(
            """
            SELECT id, title, summary, updated_at
            FROM conversations
            WHERE user_id = ? AND persona_id = ? AND status = 'active'
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (user_id, persona_id),
        ).fetchone()
        if conversation is None:
            return None
        message_rows = db.execute(
            """
            SELECT id, role, content, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id DESC
            LIMIT 12
            """,
            (int(conversation["id"]),),
        ).fetchall()

    history = [dict(row) for row in reversed(message_rows)]
    latest_message = history[-1] if history else {}
    return {
        "conversation_id": int(conversation["id"]),
        "title": str(conversation["title"] or ""),
        "summary": str(conversation["summary"] or ""),
        "history": history,
        "latest_message": latest_message,
    }


def _generate_proactive_reply(candidate: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    from .db_chat import (
        _apply_expression_policy,
        _extract_reply_presentation,
        _recent_expression_policy,
        chat_rendering_rules_prompt,
        ling_rendering_rules_prompt,
    )
    from .llm_client import call_llm_api
    from .persona_forge import build_ling_prompt

    user_id = int(candidate["user_id"])
    persona_id = int(candidate["persona_id"])
    persona_name = str(candidate.get("persona_name") or "")
    history = [
        {"role": str(item.get("role") or "assistant"), "content": str(item.get("content") or "")}
        for item in (context.get("history") or [])
        if str(item.get("content") or "").strip()
    ]
    policy = _recent_expression_policy(user_id, persona_id, int(context["conversation_id"]))
    self_use_companion = bool(candidate.get("self_use_companion"))
    persona_prompt = (
        build_ling_prompt(
            {
                "name": persona_name,
                "summary": candidate.get("persona_summary") or "",
                "relationship": candidate.get("relationship") or "",
                "speaking_style": candidate.get("speaking_style") or "",
            }
        )
        if self_use_companion
        else str(candidate.get("persona_prompt") or "")
    )
    messages = [
        {"role": "system", "content": persona_prompt},
        {
            "role": "system",
            "content": ling_rendering_rules_prompt() if self_use_companion else chat_rendering_rules_prompt(),
        },
        {
            "role": "system",
            "content": (
                "You are sending one proactive message as LING's single persistent companion. "
                if self_use_companion
                else "You are sending one proactive companion message as the current persona. "
            ) + (
                "Do not mention automation, schedules, policies, APIs, or that you were triggered. "
                "Keep it short, low-pressure, and natural. Do not demand an answer. "
                "At most one gentle question. Avoid guilt, urgency, or repeated check-ins. "
                "Return only the message text."
            ),
        },
        {
            "role": "system",
            "content": (
                f"Persona name: {persona_name}\n"
                f"Relationship: {candidate.get('relationship') or ''}\n"
                f"Speaking style: {candidate.get('speaking_style') or ''}\n"
                f"Conversation summary: {context.get('summary') or 'none'}"
            ),
        },
        *history,
        {
            "role": "user",
            "content": (
                "Send a brief proactive message now. It should feel like a natural continuation after a quiet pause."
            ),
        },
    ]
    raw = call_llm_api(messages, task="chat")
    presentation = _extract_reply_presentation(raw)
    expressions = _apply_expression_policy(presentation.get("expressions") or [], policy)
    return {"reply": presentation.get("content") or "", "expressions": expressions}


def detect_quiet_request(user_text: str) -> bool:
    """Check if user's message requests quiet mode (no proactive messages)."""
    text = str(user_text or "").lower().replace(" ", "")
    quiet_keywords = (
        "别打扰我", "安静一点", "先别说话", "静一静",
        "别说话", "安静", "不要吵", "别吵", "别打扰",
        "让我安静", "不要打扰我", "先不要说话", "别发消息",
        "别主动发消息", "不用主动找我",
        "quietmode", "silentmode", "dnd",
    )
    return any(kw in text for kw in quiet_keywords)


def get_proactive_status(user_id: int, persona_id: int) -> dict[str, Any]:
    from .user_consent import user_has_consent

    config = load_proactive_config()
    config_enabled = bool(config.get("enabled", False))
    consent_granted = bool(user_has_consent(user_id, "proactive"))
    enabled = config_enabled and consent_granted
    base = {
        "enabled": enabled,
        "config_enabled": config_enabled,
        "consent_granted": consent_granted,
        "config": config,
    }
    if not enabled:
        return base
    controller = get_proactive_controller(user_id, persona_id)
    return {**controller.get_status(), **base}
