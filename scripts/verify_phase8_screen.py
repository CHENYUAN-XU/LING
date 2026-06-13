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
                "INSERT INTO users (username, password_hash, created_at, updated_at) VALUES ('phase8', 'x', ?, ?)",
                (ts, ts),
            ).lastrowid
        )
        db.execute(
            "INSERT INTO user_profiles (user_id, nickname, created_at, updated_at) VALUES (?, 'screen_test', ?, ?)",
            (user_id, ts, ts),
        )
    return user_id


def verify_screen_config() -> None:
    import app.screen_perception as sp

    assert sp.screen_enabled() is False

    config = sp.get_screen_config()
    assert config["enabled"] is False
    assert config["capture_active_window_title"] is True
    assert config["capture_screenshot"] is False

    status = sp.get_screen_perception_status()
    assert status["config"]["enabled"] is False
    assert not status["active"]
    assert "system" in status
    assert "screenshot_available" in status["system"]


def verify_screen_context_capture() -> None:
    import app.screen_perception as sp

    context = sp.capture_screen_context()
    assert isinstance(context, dict)
    assert "window_title" in context
    assert "screenshot_available" in context
    assert "screenshot_metadata" in context
    assert "capabilities" in context

    title = sp.get_active_window_title()
    if title is not None:
        assert isinstance(title, str)


def verify_screenshot_metadata_path() -> None:
    import app.screen_perception as sp

    original_config = sp.load_config
    original_capture = sp.capture_screenshot_metadata
    try:
        sp.load_config = lambda: {
            "screen": {
                "enabled": False,
                "capture_active_window_title": False,
                "capture_screenshot": True,
                "capture_interval_seconds": 10,
            }
        }
        sp.capture_screenshot_metadata = lambda: {
            "available": True,
            "metadata": {
                "width": 1920,
                "height": 1080,
                "mode": "RGB",
                "captured_at": 1,
                "pixels_retained": False,
            },
            "error": None,
        }
        context = sp.capture_screen_context()
        assert context["screenshot_available"] is True
        assert context["screenshot_metadata"]["width"] == 1920
        assert context["screenshot_metadata"]["pixels_retained"] is False
        assert "screenshot" not in context or context.get("screenshot") is None
    finally:
        sp.load_config = original_config
        sp.capture_screenshot_metadata = original_capture


def verify_cycle_disabled(user_id: int) -> None:
    import app.screen_perception as sp

    result = sp.run_screen_perception_cycle(user_id)
    assert result["cycle"] == "disabled"


def verify_screen_requires_user_consent(user_id: int) -> None:
    import app.screen_perception as sp

    original_config = sp.load_config
    try:
        sp.load_config = lambda: {
            "screen": {
                "enabled": True,
                "capture_active_window_title": True,
                "capture_screenshot": False,
                "capture_interval_seconds": 10,
            }
        }

        assert sp.screen_enabled(user_id) is False

        status = sp.get_screen_perception_status(user_id)
        assert status["config"]["enabled"] is True
        assert status["active"] is False

        result = sp.run_screen_perception_cycle(user_id)
        assert result["cycle"] == "disabled"
    finally:
        sp.load_config = original_config


def verify_screen_context_for_chat(user_id: int) -> None:
    import app.screen_perception as sp
    import app.user_consent as consent_mod
    import app.world_state as ws

    original_config = sp.load_config
    try:
        sp.load_config = lambda: {
            "screen": {
                "enabled": True,
                "capture_active_window_title": True,
                "capture_screenshot": False,
                "capture_interval_seconds": 10,
            }
        }

        ws.store_world_observation(
            user_id=user_id,
            source="screen",
            observation_type="window_title",
            content="Visual Studio Code - project_mnemosyne",
            confidence=0.9,
        )

        assert sp.get_screen_context_for_chat(user_id) == ""

        consent_mod.grant_consent(user_id, "screen")
        context_text = sp.get_screen_context_for_chat(user_id)
        assert "Visual Studio Code" in context_text
        assert "Recent screen context" in context_text
        assert "Only reference this" in context_text

        ws.store_world_observation(
            user_id=user_id,
            source="screen",
            observation_type="window_title",
            content="Notepad - Untitled",
            confidence=0.9,
        )

        multi_context = sp.get_screen_context_for_chat(user_id)
        assert "Visual Studio Code" in multi_context
        assert "Notepad" in multi_context

        consent_mod.revoke_consent(user_id, "screen")
        assert sp.get_screen_context_for_chat(user_id) == ""
    finally:
        sp.load_config = original_config


def verify_server_endpoints(user_id: int) -> None:
    user = {"id": user_id}

    cfg = server.screen_config(user)
    assert cfg["screen"]["enabled"] is False

    status = server.screen_status(user)
    assert not status["active"]

    cycle = server.screen_perception_cycle(user)
    assert cycle["cycle"] == "disabled"


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        database.DB_PATH = Path(tmp) / "phase8_screen.db"
        database.init_db()
        user_id = seed_user()
        verify_screen_config()
        verify_screen_context_capture()
        verify_screenshot_metadata_path()
        verify_cycle_disabled(user_id)
        verify_screen_requires_user_consent(user_id)
        verify_screen_context_for_chat(user_id)
        verify_server_endpoints(user_id)
    print("Phase 8 Screen Perception verification passed")


if __name__ == "__main__":
    main()
