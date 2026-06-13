from __future__ import annotations

import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app.database as database
import app.server as server


def seed_user() -> int:
    ts = database.now_ts()
    with database.get_db() as db:
        user_id = int(
            db.execute(
                "INSERT INTO users (username, password_hash, created_at, updated_at) VALUES ('phase6', 'x', ?, ?)",
                (ts, ts),
            ).lastrowid
        )
        db.execute(
            "INSERT INTO user_profiles (user_id, nickname, created_at, updated_at) VALUES (?, 'presence_test', ?, ?)",
            (user_id, ts, ts),
        )
    return user_id


def verify_runtime_state() -> None:
    import app.runtime_state as rs

    assert rs.presence_enabled() is False

    state = rs.RuntimeState()
    assert state.current_state == "idle"
    assert state.is_quiet is False

    state.touch_interaction()
    assert state.time_since_last_interaction < 1.0

    prev = state.transition_to("thinking")
    assert prev == "thinking"
    assert state.previous_state == "idle"

    prev = state.transition_to("speaking")
    assert prev == "speaking"

    prev = state.transition_to("idle")
    assert prev == "idle"

    state.set_quiet_mode(True)
    assert state.is_quiet is True
    assert state.current_state == "quiet"

    state.set_quiet_mode(False)
    assert state.is_quiet is False
    assert state.current_state == "idle"

    snapshot = state.get_snapshot()
    assert snapshot["state"] == "idle"
    assert snapshot["quiet_mode"] is False
    assert "state_duration_seconds" in snapshot
    assert "seconds_since_last_interaction" in snapshot


def verify_presence_loop() -> None:
    import app.presence_loop as pl
    import app.runtime_state as rs

    assert pl.presence_enabled() is False

    summary = pl.get_presence_summary()
    assert summary["enabled"] is False

    result = pl.on_user_message()
    assert result["transition"] == "disabled"

    original_runtime_config = rs.load_config
    original_presence_config = pl.load_config
    original_runtime_state = rs._runtime_state
    original_scoped_states = dict(rs._runtime_states)
    try:
        rs.load_config = lambda: {"presence": {"enabled": True}}
        pl.load_config = lambda: {"presence": {"enabled": True}}

        rs._runtime_state = rs.RuntimeState()
        assert pl.on_user_message()["current"] == "thinking"
        assert pl.on_reply_start()["current"] == "speaking"
        assert pl.on_reply_end()["current"] == "idle"

        rs._runtime_state = rs.RuntimeState()
        assert pl.on_user_message()["current"] == "thinking"
        rs.get_runtime_state().set_quiet_mode(True)
        assert pl.on_reply_start()["current"] == "quiet"
        assert rs.get_runtime_state().current_state == "quiet"
        assert pl.on_reply_end()["current"] == "quiet"
        assert rs.get_runtime_state().current_state == "quiet"
        assert rs.get_runtime_state().is_quiet is True

        rs._runtime_states.clear()
        assert pl.on_user_message(user_id=1)["current"] == "thinking"
        assert pl.on_quiet_mode_enter(user_id=1)["quiet_mode"] is True
        assert pl.get_presence_summary(user_id=1)["runtime"]["quiet_mode"] is True
        assert pl.get_presence_summary(user_id=2)["runtime"]["quiet_mode"] is False
        assert pl.get_presence_summary(user_id=2)["runtime"]["state"] == "idle"
        assert pl.on_reply_start(user_id=2)["current"] == "speaking"
        assert pl.get_presence_summary(user_id=1)["runtime"]["state"] == "quiet"
    finally:
        rs.load_config = original_runtime_config
        pl.load_config = original_presence_config
        rs._runtime_state = original_runtime_state
        rs._runtime_states.clear()
        rs._runtime_states.update(original_scoped_states)

    result = pl.on_reply_start()
    assert result["transition"] == "disabled"

    result = pl.on_reply_end()
    assert result["transition"] == "disabled"

    result = pl.on_idle()
    assert result["transition"] == "disabled"

    assert pl.detect_quiet_mode_request("别打扰我") is True
    assert pl.detect_quiet_mode_request("安静一点") is True
    assert pl.detect_quiet_mode_request("先别说话") is True
    assert pl.detect_quiet_mode_request("你好") is False
    assert pl.detect_quiet_mode_request("今天天气不错") is False
    assert pl.detect_quiet_mode_request("") is False

    assert pl.should_show_presence_notice() is False


def verify_server_endpoints(user_id: int) -> None:
    user = {"id": user_id}

    state = server.presence_state(user)
    assert state["enabled"] is False

    result = server.presence_user_message(user)
    assert result["transition"] == "disabled"

    result = server.presence_reply_start(user)
    assert result["transition"] == "disabled"

    result = server.presence_reply_end(user)
    assert result["transition"] == "disabled"

    result = server.presence_idle(user)
    assert result["transition"] == "disabled"

    result = server.presence_quiet_mode(user)
    assert result["transition"] == "disabled"

    result = server.presence_normal_mode(user)
    assert result["transition"] == "disabled"

    check = server.presence_check_quiet(
        server.PresenceQuietCheckRequest(text="别打扰我"),
        user,
    )
    assert check["should_enter_quiet"] is True

    check = server.presence_check_quiet(
        server.PresenceQuietCheckRequest(text="你好啊"),
        user,
    )
    assert check["should_enter_quiet"] is False


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        database.DB_PATH = Path(tmp) / "phase6_presence.db"
        database.init_db()
        user_id = seed_user()
        verify_runtime_state()
        verify_presence_loop()
        verify_server_endpoints(user_id)
    print("Phase 6 Presence Loop verification passed")


if __name__ == "__main__":
    main()
