from __future__ import annotations

import sys
import tempfile
import types
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
                "INSERT INTO users (username, password_hash, created_at, updated_at) VALUES ('phase7', 'x', ?, ?)",
                (ts, ts),
            ).lastrowid
        )
        db.execute(
            "INSERT INTO user_profiles (user_id, nickname, created_at, updated_at) VALUES (?, 'camera_test', ?, ?)",
            (user_id, ts, ts),
        )
    return user_id


def verify_camera_config() -> None:
    import app.camera_perception as cp

    assert cp.camera_enabled() is False

    config = cp.get_camera_config()
    assert config["enabled"] is False
    assert config["detect_presence"] is False
    assert config["detect_motion"] is False
    assert config["stream_fps"] == 8
    assert config["stream_max_width"] == 640

    status = cp.get_camera_status()
    assert status["config"]["enabled"] is False
    assert isinstance(status["system"], dict)
    assert "available" in status["system"]
    assert "capture_source" in status["system"]
    assert "stream" in status
    assert status["stream"]["media_type"] == "multipart/x-mixed-replace; boundary=frame"

    metadata_only = cp.detect_person_presence({"has_content": True, "frame": None})
    assert metadata_only["person_detected"] is False
    assert metadata_only["event"] == "metadata_only"
    assert "placeholder" not in metadata_only.get("note", "")

    no_frame = cp.detect_person_presence(None)
    assert no_frame["event"] == "no_frame"


def verify_perception_disabled() -> None:
    import app.perception as perception_mod

    assert perception_mod.perception_enabled() is False


def verify_camera_requires_user_consent(user_id: int) -> None:
    import app.camera_perception as cp
    import app.perception as perception_mod

    original_camera_config = cp.load_config
    original_perception_config = perception_mod.load_config
    try:
        enabled_config = {
            "camera": {
                "enabled": True,
                "capture_source": 0,
                "detect_presence": False,
                "detect_motion": False,
                "capture_interval_seconds": 5,
            }
        }
        cp.load_config = lambda: enabled_config
        perception_mod.load_config = lambda: enabled_config

        assert cp.camera_enabled(user_id) is False
        assert perception_mod.perception_enabled(user_id) is False

        status = cp.get_camera_status(user_id)
        assert status["config"]["enabled"] is True
        assert status["active"] is False

        summary = perception_mod.get_perception_summary(user_id)
        assert summary["enabled"] is False
        assert summary["camera"]["active"] is False

        frame = cp.capture_frame(user_id=user_id)
        assert frame is None
    finally:
        cp.load_config = original_camera_config
        perception_mod.load_config = original_perception_config


def verify_consent_labels(user_id: int) -> None:
    import app.user_consent as consent_mod

    initial = consent_mod.get_all_consents(user_id)
    by_key = {item["consent_key"]: item for item in initial}
    assert by_key["camera"]["label"] == "摄像头感知"
    assert by_key["screen"]["label"] == "屏幕感知"
    assert by_key["proactive"]["label"] == "主动消息"
    assert by_key["camera"]["granted"] is False

    granted = consent_mod.grant_consent(user_id, "camera")
    assert granted["label"] == "摄像头感知"
    assert granted["granted"] is True

    after = {item["consent_key"]: item for item in consent_mod.get_all_consents(user_id)}
    assert after["camera"]["label"] == "摄像头感知"
    assert after["camera"]["granted"] is True


def verify_world_state(user_id: int) -> None:
    import app.world_state as ws

    obs = ws.store_world_observation(
        user_id=user_id,
        source="camera",
        observation_type="user_presence",
        content="User detected in camera frame",
        confidence=0.8,
    )
    assert obs["source"] == "camera"
    assert obs["observation_type"] == "user_presence"
    assert obs["content"] == "User detected in camera frame"
    assert obs["confidence"] == 0.8

    low_confidence = ws.store_world_observation(
        user_id=user_id,
        source="camera",
        observation_type="test_low_confidence",
        content="low",
        confidence=-10,
    )
    assert low_confidence["confidence"] == 0.0

    high_confidence = ws.store_world_observation(
        user_id=user_id,
        source="camera",
        observation_type="test_high_confidence",
        content="high",
        confidence=99,
    )
    assert high_confidence["confidence"] == 1.0

    obs2 = ws.store_world_observation(
        user_id=user_id,
        source="screen",
        observation_type="window_title",
        content="Visual Studio Code - project-mnemosyne",
        confidence=0.9,
    )
    assert obs2["source"] == "screen"

    recent = ws.get_recent_world_observations(user_id, limit=10)
    assert len(recent) == 4
    sources = {obs["source"] for obs in recent}
    assert sources == {"camera", "screen"}

    camera_only = ws.get_recent_world_observations(user_id, source="camera")
    assert len(camera_only) == 3
    assert "user_presence" in {item["observation_type"] for item in camera_only}

    fallback_limit = ws.get_recent_world_observations(user_id, limit="not-a-number")
    assert len(fallback_limit) == 4

    presence_only = ws.get_recent_world_observations(user_id, observation_type="user_presence")
    assert len(presence_only) == 1

    summary = ws.get_world_state_summary(user_id)
    assert summary["total_observations"] == 4
    assert "camera" in summary["sources"]
    assert "screen" in summary["sources"]


def verify_server_endpoints(user_id: int) -> None:
    from fastapi import HTTPException

    user = {"id": user_id}

    cfg = server.camera_config(user)
    assert cfg["camera"]["enabled"] is False

    status = server.camera_status(user)
    assert "config" in status
    assert "system" in status

    summary = server.perception_summary(user)
    assert summary["enabled"] is False

    cycle = server.perception_cycle(user)
    assert cycle["cycle"] == "disabled"

    obs = server.world_observations(user, limit=5)
    assert "observations" in obs

    ws_summary = server.world_state_summary(user)
    assert "total_observations" in ws_summary

    try:
        server.camera_stream(user)
        raise AssertionError("should reject camera stream when disabled")
    except HTTPException as exc:
        assert exc.status_code == 400


def verify_camera_stream_endpoint(user_id: int) -> None:
    user = {"id": user_id}
    original_enabled = server.camera_enabled
    original_status = server.get_camera_status
    original_iter = server.iter_camera_mjpeg
    try:
        server.camera_enabled = lambda checked_user_id=None: True
        server.get_camera_status = lambda checked_user_id=None: {
            "stream": {"available": True},
            "system": {"error": None},
        }
        server.iter_camera_mjpeg = lambda checked_user_id: iter([b"--frame\r\nContent-Type: image/jpeg\r\n\r\nx\r\n"])
        response = server.camera_stream(user)
        assert response.media_type == "multipart/x-mixed-replace; boundary=frame"
        assert response.body_iterator is not None
    finally:
        server.camera_enabled = original_enabled
        server.get_camera_status = original_status
        server.iter_camera_mjpeg = original_iter


def verify_camera_stream_stops_after_consent_revoked(user_id: int) -> None:
    import app.camera_perception as cp

    class FakeFrame:
        shape = (480, 640, 3)

    class FakeEncoded:
        def tobytes(self) -> bytes:
            return b"jpeg"

    class FakeCapture:
        released = False

        def __init__(self, source):
            self.source = source

        def isOpened(self):
            return True

        def read(self):
            return True, FakeFrame()

        def release(self):
            FakeCapture.released = True

    fake_cv2 = types.SimpleNamespace(
        VideoCapture=FakeCapture,
        IMWRITE_JPEG_QUALITY=1,
        resize=lambda frame, size: frame,
        imencode=lambda ext, frame, params: (True, FakeEncoded()),
    )

    original_cv2 = sys.modules.get("cv2")
    original_enabled = cp.camera_enabled
    original_config = cp.get_camera_config
    calls = {"enabled": 0}

    def fake_enabled(checked_user_id=None):
        calls["enabled"] += 1
        return calls["enabled"] <= 2

    try:
        sys.modules["cv2"] = fake_cv2
        cp.camera_enabled = fake_enabled
        cp.get_camera_config = lambda: {
            "enabled": True,
            "capture_source": 0,
            "detect_presence": False,
            "detect_motion": False,
            "capture_interval_seconds": 5,
            "stream_fps": 8,
            "stream_max_width": 640,
        }

        stream = cp.iter_camera_mjpeg(user_id)
        first = next(stream)
        assert b"Content-Type: image/jpeg" in first
        try:
            next(stream)
            raise AssertionError("stream should stop after camera consent is revoked")
        except StopIteration:
            pass
        assert FakeCapture.released is True
    finally:
        cp.camera_enabled = original_enabled
        cp.get_camera_config = original_config
        if original_cv2 is None:
            sys.modules.pop("cv2", None)
        else:
            sys.modules["cv2"] = original_cv2


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        database.DB_PATH = Path(tmp) / "phase7_camera.db"
        database.init_db()
        user_id = seed_user()
        verify_camera_config()
        verify_perception_disabled()
        verify_camera_requires_user_consent(user_id)
        verify_consent_labels(user_id)
        verify_world_state(user_id)
        verify_server_endpoints(user_id)
        verify_camera_stream_endpoint(user_id)
        verify_camera_stream_stops_after_consent_revoked(user_id)
    print("Phase 7 Camera Perception verification passed")


if __name__ == "__main__":
    main()
