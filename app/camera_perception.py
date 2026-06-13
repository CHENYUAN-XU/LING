from __future__ import annotations

import time
from typing import Any

from .config import load_config


def camera_enabled(user_id: int | None = None) -> bool:
    config = load_config()
    camera_cfg = config.get("camera", {}) or {}
    if not bool(camera_cfg.get("enabled", False)):
        return False
    if user_id is not None:
        from .user_consent import user_has_consent
        if not user_has_consent(user_id, "camera"):
            return False
    return True


def get_camera_config() -> dict[str, Any]:
    config = load_config()
    camera_cfg = config.get("camera", {}) or {}
    if not isinstance(camera_cfg, dict):
        camera_cfg = {}
    return {
        "enabled": bool(camera_cfg.get("enabled", False)),
        "capture_source": camera_cfg.get("capture_source", 0),
        "detect_presence": bool(camera_cfg.get("detect_presence", False)),
        "detect_motion": bool(camera_cfg.get("detect_motion", False)),
        "capture_interval_seconds": int(camera_cfg.get("capture_interval_seconds", 5)),
        "stream_fps": int(camera_cfg.get("stream_fps", 8)),
        "stream_max_width": int(camera_cfg.get("stream_max_width", 640)),
    }


def check_camera_availability() -> dict[str, Any]:
    """Check if camera is available on the system. Returns diagnostic info."""
    config = get_camera_config()
    source = config.get("capture_source", 0)
    result: dict[str, Any] = {
        "available": False,
        "error": None,
        "cv2_available": False,
        "capture_source": source,
    }

    cap = None
    try:
        import cv2
        result["cv2_available"] = True
        cap = cv2.VideoCapture(source)
        if cap.isOpened():
            result["available"] = True
        else:
            result["error"] = "camera not accessible"
    except ImportError:
        result["error"] = "opencv-python not installed"
    except Exception as exc:
        result["error"] = str(exc)
    finally:
        try:
            if cap is not None:
                cap.release()
        except Exception:
            pass
        try:
            import cv2
            cv2.destroyAllWindows()
        except Exception:
            pass

    return result


def capture_frame(capture_source: int = 0, user_id: int | None = None) -> dict[str, Any] | None:
    """Capture a single camera frame. Returns metadata, not image bytes."""
    return _capture_frame(capture_source, user_id=user_id, include_frame=False)


def _capture_frame(capture_source: int = 0, user_id: int | None = None, include_frame: bool = False) -> dict[str, Any] | None:
    if not camera_enabled(user_id):
        return None

    try:
        import cv2
    except ImportError:
        return {"error": "opencv-python not installed", "frame": None}

    cap = None
    try:
        cap = cv2.VideoCapture(capture_source)
        if not cap.isOpened():
            return {"error": "camera not available", "frame": None}

        ret, frame = cap.read()

        if not ret:
            return {"error": "failed to read frame", "frame": None}

        result = {
            "frame": None,
            "shape": tuple(int(v) for v in getattr(frame, "shape", ()) or ()),
            "timestamp": None,
            "has_content": True,
        }
        if include_frame:
            result["frame"] = frame
        return result
    except Exception as exc:
        return {"error": str(exc), "frame": None}
    finally:
        try:
            if cap is not None:
                cap.release()
        except Exception:
            pass


def detect_person_presence(frame_data: Any = None) -> dict[str, Any]:
    """Detect whether a person is present in frame. Returns presence event info."""
    if not frame_data or not isinstance(frame_data, dict):
        return _presence_result(False, "no_frame", "no frame data supplied")
    frame = frame_data.get("frame")
    if frame is None:
        if frame_data.get("has_content"):
            return _presence_result(False, "metadata_only", "frame pixels were not retained for privacy")
        return _presence_result(False, "no_frame", str(frame_data.get("error") or "no frame content"))

    try:
        import cv2
    except ImportError:
        return _presence_result(False, "cv2_missing", "opencv-python not installed")

    try:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        classifier = cv2.CascadeClassifier(cascade_path)
        if classifier.empty():
            return _presence_result(False, "classifier_missing", "OpenCV face cascade not available")
        faces = classifier.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        face_count = int(len(faces))
        if face_count > 0:
            return {
                "person_detected": True,
                "event": "face_detected",
                "confidence": 0.75,
                "face_count": face_count,
                "detector": "opencv_haar_frontalface",
            }
        return {
            "person_detected": False,
            "event": "no_face_detected",
            "confidence": 0.4,
            "face_count": 0,
            "detector": "opencv_haar_frontalface",
        }
    except Exception as exc:
        return _presence_result(False, "detection_error", str(exc))


def _presence_result(person_detected: bool, event: str | None, note: str) -> dict[str, Any]:
    return {
        "person_detected": person_detected,
        "event": event,
        "confidence": 0.0,
        "note": note,
    }


def get_camera_status(user_id: int | None = None) -> dict[str, Any]:
    config = get_camera_config()
    availability = check_camera_availability()
    active = camera_enabled(user_id) and availability.get("available", False)
    return {
        "config": config,
        "system": availability,
        "active": active,
        "stream": {
            "available": active and availability.get("cv2_available", False),
            "media_type": "multipart/x-mixed-replace; boundary=frame",
            "fps": config.get("stream_fps", 8),
            "max_width": config.get("stream_max_width", 640),
        },
    }


def iter_camera_mjpeg(user_id: int, capture_source: int | None = None):
    """Yield an MJPEG stream from the local camera.

    Frames are encoded in memory and streamed to the local browser only; this
    function does not persist image bytes.
    """
    config = get_camera_config()
    source = config.get("capture_source", 0) if capture_source is None else capture_source
    fps = max(1, min(30, int(config.get("stream_fps", 8) or 8)))
    max_width = max(160, int(config.get("stream_max_width", 640) or 640))
    delay = 1.0 / fps

    if not camera_enabled(user_id):
        raise PermissionError("camera is disabled or not authorized")

    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("opencv-python not installed") from exc

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        try:
            cap.release()
        except Exception:
            pass
        raise RuntimeError("camera not available")

    try:
        while True:
            if not camera_enabled(user_id):
                break

            ret, frame = cap.read()
            if not ret:
                time.sleep(delay)
                continue

            height, width = frame.shape[:2]
            if width > max_width:
                scale = max_width / float(width)
                frame = cv2.resize(frame, (max_width, max(1, int(height * scale))))

            ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if ok:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Cache-Control: no-store\r\n\r\n"
                    + encoded.tobytes()
                    + b"\r\n"
                )
            time.sleep(delay)
    finally:
        cap.release()
