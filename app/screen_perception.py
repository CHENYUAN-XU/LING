from __future__ import annotations

import sys
import time
from typing import Any

from .config import load_config
from .world_state import store_world_observation


def screen_enabled(user_id: int | None = None) -> bool:
    config = load_config()
    screen_cfg = config.get("screen", {}) or {}
    if not bool(screen_cfg.get("enabled", False)):
        return False
    if user_id is not None:
        from .user_consent import user_has_consent
        if not user_has_consent(user_id, "screen"):
            return False
    return True


def get_screen_config() -> dict[str, Any]:
    config = load_config()
    screen_cfg = config.get("screen", {}) or {}
    if not isinstance(screen_cfg, dict):
        screen_cfg = {}
    return {
        "enabled": bool(screen_cfg.get("enabled", False)),
        "capture_active_window_title": bool(screen_cfg.get("capture_active_window_title", True)),
        "capture_screenshot": bool(screen_cfg.get("capture_screenshot", False)),
        "capture_interval_seconds": int(screen_cfg.get("capture_interval_seconds", 10)),
    }


def get_active_window_title() -> str | None:
    """Get the title of the currently active window."""
    if sys.platform != "win32":
        return None

    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None

        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return None

        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value
    except Exception as exc:
        print(f"[ScreenPerception] failed to get window title: {exc}")
        return None


def check_screen_capabilities() -> dict[str, Any]:
    result: dict[str, Any] = {
        "platform": sys.platform,
        "active_window_title_available": sys.platform == "win32",
        "screenshot_available": False,
        "screenshot_error": None,
    }
    try:
        from PIL import ImageGrab

        result["screenshot_available"] = True
    except ImportError:
        result["screenshot_error"] = "Pillow not installed"
    except Exception as exc:
        result["screenshot_error"] = str(exc)
    return result


def capture_screen_context() -> dict[str, Any]:
    """Capture current screen context (window title only by default)."""
    config = get_screen_config()
    result: dict[str, Any] = {
        "window_title": None,
        "screenshot_available": False,
        "screenshot_metadata": None,
        "ocr_text": None,
        "error": None,
        "capabilities": check_screen_capabilities(),
    }

    if config.get("capture_active_window_title"):
        try:
            title = get_active_window_title()
            result["window_title"] = title
        except Exception as exc:
            result["error"] = str(exc)

    if config.get("capture_screenshot"):
        screenshot = capture_screenshot_metadata()
        result["screenshot_available"] = bool(screenshot.get("available"))
        result["screenshot_metadata"] = screenshot.get("metadata")
        if screenshot.get("error"):
            result["error"] = screenshot.get("error")

    return result


def capture_screenshot_metadata() -> dict[str, Any]:
    """Capture screenshot metadata without returning or storing pixels."""
    try:
        from PIL import ImageGrab
    except ImportError:
        return {"available": False, "metadata": None, "error": "Pillow not installed"}

    try:
        image = ImageGrab.grab()
        metadata = {
            "width": int(getattr(image, "width", 0) or 0),
            "height": int(getattr(image, "height", 0) or 0),
            "mode": str(getattr(image, "mode", "")),
            "captured_at": int(time.time()),
            "pixels_retained": False,
        }
        try:
            image.close()
        except Exception:
            pass
        return {"available": True, "metadata": metadata, "error": None}
    except Exception as exc:
        return {"available": False, "metadata": None, "error": str(exc)}


def run_screen_perception_cycle(user_id: int) -> dict[str, Any]:
    """Run one perception cycle for screen context. Stores in world_state."""
    if not screen_enabled(user_id):
        return {"cycle": "disabled"}

    context = capture_screen_context()
    observations = []

    if context.get("window_title"):
        obs = store_world_observation(
            user_id=user_id,
            source="screen",
            observation_type="window_title",
            content=str(context["window_title"]),
            confidence=0.9,
            metadata={"source": "screen_perception"},
        )
        observations.append(obs)

    return {
        "cycle": "completed",
        "context": context,
        "observations": observations,
    }


def get_screen_perception_status(user_id: int | None = None) -> dict[str, Any]:
    config = get_screen_config()
    active = screen_enabled(user_id) if user_id is not None else screen_enabled()
    capabilities = check_screen_capabilities()
    return {
        "config": config,
        "platform": sys.platform,
        "window_title_available": capabilities["active_window_title_available"],
        "system": capabilities,
        "active": active,
    }


def get_screen_context_for_chat(user_id: int) -> str:
    """Get recent screen observations formatted for chat context injection."""
    if not screen_enabled(user_id):
        return ""

    from .world_state import get_recent_world_observations

    observations = get_recent_world_observations(
        user_id,
        source="screen",
        observation_type="window_title",
        limit=3,
    )

    if not observations:
        return ""

    titles = [str(obs.get("content") or "") for obs in observations if obs.get("content")]
    if not titles:
        return ""

    return (
        "Recent screen context (user's active window titles):\n"
        + "\n".join(f"- {title}" for title in titles)
        + "\n- Only reference this when the user asks about what's on their screen."
    )
