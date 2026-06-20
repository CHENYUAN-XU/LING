from __future__ import annotations

import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app.database as database
import app.server as server


def seed_user_and_persona() -> tuple[int, int]:
    ts = database.now_ts()
    with database.get_db() as db:
        user_id = int(
            db.execute(
                "INSERT INTO users (username, password_hash, created_at, updated_at) VALUES ('phase9', 'x', ?, ?)",
                (ts, ts),
            ).lastrowid
        )
        db.execute(
            "INSERT INTO user_profiles (user_id, nickname, created_at, updated_at) VALUES (?, 'proactive_test', ?, ?)",
            (user_id, ts, ts),
        )
        persona_id = int(
            db.execute(
                """
                INSERT INTO personas (user_id, name, summary, prompt, relationship, speaking_style, created_at, updated_at)
                VALUES (?, '清和', '安静', '自然聊天', '朋友', '短句', ?, ?)
                """,
                (user_id, ts, ts),
            ).lastrowid
        )
    return user_id, persona_id


def seed_second_user_and_persona() -> tuple[int, int]:
    ts = database.now_ts()
    with database.get_db() as db:
        user_id = int(
            db.execute(
                "INSERT INTO users (username, password_hash, created_at, updated_at) VALUES ('phase9-other', 'x', ?, ?)",
                (ts, ts),
            ).lastrowid
        )
        db.execute(
            "INSERT INTO user_profiles (user_id, nickname, created_at, updated_at) VALUES (?, 'other_user', ?, ?)",
            (user_id, ts, ts),
        )
        persona_id = int(
            db.execute(
                """
                INSERT INTO personas (user_id, name, summary, prompt, relationship, speaking_style, created_at, updated_at)
                VALUES (?, '远声', '边界测试', '自然聊天', '朋友', '短句', ?, ?)
                """,
                (user_id, ts, ts),
            ).lastrowid
        )
    return user_id, persona_id


def verify_proactive_config() -> None:
    import app.proactive as pm

    assert pm.proactive_enabled() is False

    config = pm.load_proactive_config()
    assert config["enabled"] is False
    assert config["min_interval_seconds"] == 300
    assert config["cooldown_after_negative_seconds"] == 1800
    assert config["max_per_hour"] == 3
    assert config["scheduler_enabled"] is False
    assert config["scheduler_interval_seconds"] == 300


def verify_proactive_scheduler_defaults() -> None:
    import app.proactive as pm

    pm.stop_proactive_scheduler()
    status = pm.get_proactive_scheduler_status()
    assert status["running"] is False
    assert status["scheduler_enabled"] is False

    start = pm.start_proactive_scheduler()
    assert start["running"] is False
    assert start["reason"] == "scheduler_disabled"


def verify_proactive_scheduler_opt_in() -> None:
    import app.proactive as pm

    original_config = pm.load_config
    try:
        pm.load_config = lambda: {
            "proactive": {
                "enabled": True,
                "scheduler_enabled": True,
                "scheduler_interval_seconds": 60,
            }
        }
        started = pm.start_proactive_scheduler()
        assert started["running"] is True
        assert started["scheduler_enabled"] is True

        repeated = pm.start_proactive_scheduler()
        assert repeated["running"] is True
        assert repeated["reason"] == "already_running"

        stopped = pm.stop_proactive_scheduler()
        assert stopped["running"] is False
    finally:
        pm.stop_proactive_scheduler()
        pm.load_config = original_config


def verify_proactive_controller(user_id: int, persona_id: int) -> None:
    import app.proactive as pm

    controller = pm.get_proactive_controller(user_id, persona_id)
    assert controller is not None

    assert controller.is_quiet is False

    can_send = controller.can_send_proactive()
    assert can_send["allowed"] is False
    assert can_send["reason"] == "proactive_disabled"

    status = controller.get_status()
    assert status["config"]["enabled"] is False
    assert status["state"]["quiet_mode"] is False
    assert status["state"]["user_positive_count"] == 0
    assert status["state"]["user_negative_count"] == 0


def verify_quiet_detection() -> None:
    import app.proactive as pm

    assert pm.detect_quiet_request("别打扰我") is True
    assert pm.detect_quiet_request("安静一点") is True
    assert pm.detect_quiet_request("先别说话") is True
    assert pm.detect_quiet_request("别主动发消息") is True
    assert pm.detect_quiet_request("不用主动找我") is True
    assert pm.detect_quiet_request("你好") is False
    assert pm.detect_quiet_request("今天天气") is False
    assert pm.detect_quiet_request("") is False


def verify_server_endpoints(user_id: int, persona_id: int) -> None:
    from fastapi import HTTPException

    user = {"id": user_id}

    status = server.proactive_status(user, persona_id)
    assert status["enabled"] is False

    scheduler = server.proactive_scheduler_status(user)
    assert scheduler["running"] is False
    assert scheduler["scheduler_enabled"] is False

    can_send = server.proactive_can_send(
        server.ProactiveCheckRequest(persona_id=persona_id),
        user,
    )
    assert can_send["allowed"] is False
    assert can_send["reason"] == "proactive_disabled"

    try:
        server.proactive_on_sent(
            server.ProactiveCheckRequest(persona_id=persona_id),
            user,
        )
        raise AssertionError("should fail when proactive is disabled")
    except HTTPException as exc:
        assert exc.status_code == 400

    try:
        server.proactive_feedback(
            server.ProactiveFeedbackRequest(persona_id=persona_id, positive=True),
            user,
        )
        raise AssertionError("should fail when proactive is disabled")
    except HTTPException as exc:
        assert exc.status_code == 400

    try:
        server.proactive_quiet_mode(
            server.ProactiveQuietRequest(persona_id=persona_id, quiet=True),
            user,
        )
        raise AssertionError("should fail when proactive is disabled")
    except HTTPException as exc:
        assert exc.status_code == 400

    check = server.proactive_check_quiet(
        server.PresenceQuietCheckRequest(text="别打扰我"),
        user,
    )
    assert check["should_enter_quiet"] is True


def verify_persona_ownership_boundary(user_id: int, other_persona_id: int) -> None:
    from fastapi import HTTPException

    user = {"id": user_id}
    original_enabled = server.proactive_enabled
    server.proactive_enabled = lambda *args, **kwargs: True
    try:
        for call in (
            lambda: server.proactive_status(user, other_persona_id),
            lambda: server.proactive_can_send(server.ProactiveCheckRequest(persona_id=other_persona_id), user),
            lambda: server.proactive_on_sent(server.ProactiveCheckRequest(persona_id=other_persona_id), user),
            lambda: server.proactive_feedback(
                server.ProactiveFeedbackRequest(persona_id=other_persona_id, positive=True),
                user,
            ),
            lambda: server.proactive_quiet_mode(
                server.ProactiveQuietRequest(persona_id=other_persona_id, quiet=True),
                user,
            ),
        ):
            try:
                call()
                raise AssertionError("should reject another user's persona")
            except HTTPException as exc:
                assert exc.status_code == 404
    finally:
        server.proactive_enabled = original_enabled


def verify_proactive_requires_user_consent(user_id: int, persona_id: int) -> None:
    from fastapi import HTTPException

    user = {"id": user_id}
    original_enabled = server.proactive_enabled
    server.proactive_enabled = lambda checked_user_id=None: checked_user_id is None
    try:
        can_send = server.proactive_can_send(
            server.ProactiveCheckRequest(persona_id=persona_id),
            user,
        )
        assert can_send["allowed"] is False
        assert can_send["reason"] == "proactive_disabled"

        try:
            server.proactive_on_sent(
                server.ProactiveCheckRequest(persona_id=persona_id),
                user,
            )
            raise AssertionError("should fail without user consent")
        except HTTPException as exc:
            assert exc.status_code == 400
    finally:
        server.proactive_enabled = original_enabled


def verify_proactive_config_and_consent(user_id: int, persona_id: int) -> None:
    import app.proactive as pm
    import app.user_consent as consent_mod

    original_config = pm.load_config
    try:
        pm.load_config = lambda: {
            "proactive": {
                "enabled": True,
                "min_interval_seconds": 0,
                "cooldown_after_negative_seconds": 0,
                "max_per_hour": 3,
                "quiet_mode_enabled": False,
            }
        }

        assert pm.proactive_enabled(user_id) is False
        assert pm.get_proactive_controller(user_id, persona_id).can_send_proactive()["reason"] == "proactive_disabled"
        disabled_status = pm.get_proactive_status(user_id, persona_id)
        assert disabled_status["enabled"] is False
        assert disabled_status["config_enabled"] is True
        assert disabled_status["consent_granted"] is False

        consent_mod.grant_consent(user_id, "proactive")
        assert pm.proactive_enabled(user_id) is True
        enabled_status = pm.get_proactive_status(user_id, persona_id)
        assert enabled_status["enabled"] is True
        assert enabled_status["config_enabled"] is True
        assert enabled_status["consent_granted"] is True
        can_send = pm.get_proactive_controller(user_id, persona_id).can_send_proactive()
        assert can_send["allowed"] is True

        consent_mod.revoke_consent(user_id, "proactive")
        assert pm.proactive_enabled(user_id) is False
        assert pm.get_proactive_controller(user_id, persona_id).can_send_proactive()["reason"] == "proactive_disabled"
    finally:
        pm.load_config = original_config


def verify_proactive_tick_generates_message(user_id: int, persona_id: int) -> None:
    import app.llm_client as llm_client
    import app.proactive as pm
    import app.user_consent as consent_mod

    ts = database.now_ts() - 3600
    with database.get_db() as db:
        conversation_id = int(
            db.execute(
                """
                INSERT INTO conversations (user_id, persona_id, title, created_at, updated_at)
                VALUES (?, ?, 'proactive tick', ?, ?)
                """,
                (user_id, persona_id, ts, ts),
            ).lastrowid
        )
        db.execute(
            """
            INSERT INTO messages (conversation_id, user_id, persona_id, role, content, created_at)
            VALUES (?, ?, ?, 'user', '今天有点累，晚点再聊。', ?)
            """,
            (conversation_id, user_id, persona_id, ts),
        )

    original_config = pm.load_config
    original_llm = llm_client.call_llm_api
    try:
        pm.load_config = lambda: {
            "proactive": {
                "enabled": True,
                "min_interval_seconds": 0,
                "cooldown_after_negative_seconds": 0,
                "max_per_hour": 3,
                "quiet_mode_enabled": False,
                "min_user_idle_seconds": 0,
                "max_messages_per_tick": 1,
                "max_candidate_personas": 5,
            }
        }
        llm_client.call_llm_api = lambda messages, task="chat": "我刚想到你。要是现在忙，也不用急着回。"
        consent_mod.grant_consent(user_id, "proactive")

        dry = pm.run_proactive_tick(user_id=user_id, persona_id=persona_id, dry_run=True)
        assert dry["enabled"] is True
        assert dry["sent"] == 0
        assert dry["skipped"][0]["reason"] == "dry_run_ready"

        with database.get_db() as db:
            before_count = int(
                db.execute(
                    "SELECT COUNT(*) AS c FROM messages WHERE conversation_id = ? AND role = 'assistant'",
                    (conversation_id,),
                ).fetchone()["c"]
            )
            latest_message_id = int(
                db.execute(
                    "SELECT COALESCE(MAX(id), 0) AS latest_message_id FROM messages WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()["latest_message_id"]
            )
            db.execute(
                """
                UPDATE conversations
                SET last_read_message_id = ?, last_read_at = ?
                WHERE id = ?
                """,
                (latest_message_id, database.now_ts(), conversation_id),
            )
        assert before_count == 0

        result = pm.run_proactive_tick(user_id=user_id, persona_id=persona_id)
        assert result["enabled"] is True
        assert result["sent"] == 1
        sent = result["messages"][0]
        assert sent["conversation_id"] == conversation_id
        assert sent["reply"] == "我刚想到你。要是现在忙，也不用急着回。"

        with database.get_db() as db:
            assistant = db.execute(
                """
                SELECT content FROM messages
                WHERE conversation_id = ? AND role = 'assistant'
                ORDER BY id DESC LIMIT 1
                """,
                (conversation_id,),
            ).fetchone()
            state = db.execute(
                """
                SELECT last_proactive_at, proactive_count_this_hour
                FROM proactive_state
                WHERE user_id = ? AND persona_id = ?
                """,
                (user_id, persona_id),
            ).fetchone()
            unread_count = int(
                db.execute(
                    """
                    SELECT COUNT(*) AS c
                    FROM messages
                    JOIN conversations ON conversations.id = messages.conversation_id
                    WHERE messages.conversation_id = ?
                      AND messages.role = 'assistant'
                      AND messages.id > conversations.last_read_message_id
                    """,
                    (conversation_id,),
                ).fetchone()["c"]
            )
        assert assistant["content"] == "我刚想到你。要是现在忙，也不用急着回。"
        assert int(state["last_proactive_at"]) > 0
        assert int(state["proactive_count_this_hour"]) == 1
        assert unread_count == 1

        server_dry = server.proactive_tick(
            server.ProactiveTickRequest(persona_id=persona_id, dry_run=True),
            {"id": user_id},
        )
        assert server_dry["enabled"] is True
        assert server_dry["sent"] == 0
    finally:
        pm.load_config = original_config
        llm_client.call_llm_api = original_llm


def verify_proactive_rechecks_consent_before_write(user_id: int, persona_id: int) -> None:
    import app.llm_client as llm_client
    import app.proactive as pm
    import app.user_consent as consent_mod

    ts = database.now_ts() - 3600
    with database.get_db() as db:
        conversation_id = int(
            db.execute(
                """
                INSERT INTO conversations (user_id, persona_id, title, created_at, updated_at)
                VALUES (?, ?, 'proactive consent race', ?, ?)
                """,
                (user_id, persona_id, ts, ts),
            ).lastrowid
        )
        db.execute(
            """
            INSERT INTO messages (conversation_id, user_id, persona_id, role, content, created_at)
            VALUES (?, ?, ?, 'user', '晚点聊。', ?)
            """,
            (conversation_id, user_id, persona_id, ts),
        )

    original_config = pm.load_config
    original_llm = llm_client.call_llm_api
    try:
        pm.load_config = lambda: {
            "proactive": {
                "enabled": True,
                "min_interval_seconds": 0,
                "cooldown_after_negative_seconds": 0,
                "max_per_hour": 3,
                "quiet_mode_enabled": False,
                "min_user_idle_seconds": 0,
                "max_messages_per_tick": 1,
                "max_candidate_personas": 5,
            }
        }

        def revoke_during_generation(messages, task="chat"):
            consent_mod.revoke_consent(user_id, "proactive")
            return "我在。"

        llm_client.call_llm_api = revoke_during_generation
        consent_mod.grant_consent(user_id, "proactive")

        result = pm.run_proactive_tick(user_id=user_id, persona_id=persona_id)
        assert result["sent"] == 0
        assert result["skipped"][0]["reason"] == "proactive_disabled"

        with database.get_db() as db:
            assistant_count = int(
                db.execute(
                    "SELECT COUNT(*) AS c FROM messages WHERE conversation_id = ? AND role = 'assistant'",
                    (conversation_id,),
                ).fetchone()["c"]
            )
        assert assistant_count == 0
    finally:
        pm.load_config = original_config
        llm_client.call_llm_api = original_llm


def verify_self_use_companion_boundary(user_id: int, persona_id: int) -> None:
    from fastapi import HTTPException

    ts = database.now_ts() + 10
    with database.get_db() as db:
        legacy_persona_id = int(
            db.execute(
                """
                INSERT INTO personas (user_id, name, summary, prompt, relationship, speaking_style, created_at, updated_at)
                VALUES (?, 'Legacy Proactive', 'legacy', 'legacy', '', '', ?, ?)
                """,
                (user_id, ts, ts),
            ).lastrowid
        )
        server._set_self_use_companion_binding(db, user_id, persona_id)

    original_load_config = server.load_config
    original_get_status = server.get_proactive_status
    original_run_tick = server.run_proactive_tick
    original_enabled = server.proactive_enabled
    try:
        server.load_config = lambda: {
            "self_use": {
                "enabled": True,
                "username": "phase9",
                "seed_default_persona": True,
                "default_persona_name": "澪",
            }
        }
        server.get_proactive_status = lambda checked_user_id, checked_persona_id: {
            "user_id": checked_user_id,
            "persona_id": checked_persona_id,
        }
        server.run_proactive_tick = lambda **kwargs: kwargs
        server.proactive_enabled = lambda *_args, **_kwargs: True
        user = {"id": user_id, "username": "phase9"}

        assert server.proactive_status(user)["persona_id"] == persona_id
        tick = server.proactive_tick(server.ProactiveTickRequest(dry_run=True), user)
        assert tick["persona_id"] == persona_id

        for call in (
            lambda: server.proactive_status(user, legacy_persona_id),
            lambda: server.proactive_can_send(server.ProactiveCheckRequest(persona_id=legacy_persona_id), user),
            lambda: server.proactive_tick(server.ProactiveTickRequest(persona_id=legacy_persona_id, dry_run=True), user),
        ):
            try:
                call()
                raise AssertionError("LING self-use proactive must reject legacy same-owner personas")
            except HTTPException as exc:
                assert exc.status_code == 404
                assert "self-use mode" in str(exc.detail)
    finally:
        server.load_config = original_load_config
        server.get_proactive_status = original_get_status
        server.run_proactive_tick = original_run_tick
        server.proactive_enabled = original_enabled


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        database.DB_PATH = Path(tmp) / "phase9_proactive.db"
        database.init_db()
        user_id, persona_id = seed_user_and_persona()
        _, other_persona_id = seed_second_user_and_persona()
        verify_proactive_config()
        verify_proactive_scheduler_defaults()
        verify_proactive_scheduler_opt_in()
        verify_proactive_controller(user_id, persona_id)
        verify_quiet_detection()
        verify_server_endpoints(user_id, persona_id)
        verify_persona_ownership_boundary(user_id, other_persona_id)
        verify_proactive_requires_user_consent(user_id, persona_id)
        verify_proactive_config_and_consent(user_id, persona_id)
        verify_proactive_tick_generates_message(user_id, persona_id)
        verify_proactive_rechecks_consent_before_write(user_id, persona_id)
        verify_self_use_companion_boundary(user_id, persona_id)
    print("Phase 9 Proactive Companion verification passed")


if __name__ == "__main__":
    main()
