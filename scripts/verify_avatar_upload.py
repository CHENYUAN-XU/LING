from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app.database as database


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        database.DB_PATH = root / "avatar-upload.db"
        database.init_db()

        import app.server as server

        server.UPLOAD_DIR = root / "uploads"
        server.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        original_load_config = server.load_config
        server.load_config = lambda: {"self_use": {"enabled": False}}

        client = TestClient(server.app)
        registered = client.post(
            "/api/auth/register",
            json={"username": "avatar-user", "password": "password123", "nickname": "Avatar"},
        )
        assert registered.status_code == 200
        user_id = int(registered.json()["user"]["id"])

        png_bytes = b"\x89PNG\r\n\x1a\n" + b"mnemosyne-avatar"
        ok = client.post(
            "/api/uploads/avatar",
            files={"file": ("avatar.png", png_bytes, "image/png")},
        )
        assert ok.status_code == 200
        url = ok.json()["url"]
        assert url.startswith(f"/uploads/{user_id}/")
        saved = server.UPLOAD_DIR / str(user_id) / Path(url).name
        assert saved.read_bytes() == png_bytes

        spoofed = client.post(
            "/api/uploads/avatar",
            files={"file": ("fake.png", b"not really an image", "image/png")},
        )
        assert spoofed.status_code == 400
        assert "does not match" in spoofed.json()["detail"]

        wrong_type = client.post(
            "/api/uploads/avatar",
            files={"file": ("avatar.txt", b"plain text", "text/plain")},
        )
        assert wrong_type.status_code == 400

        oversized = client.post(
            "/api/uploads/avatar",
            files={"file": ("large.gif", b"GIF89a" + b"x" * server.AVATAR_MAX_BYTES, "image/gif")},
        )
        assert oversized.status_code == 400
        assert "5MB" in oversized.json()["detail"]

        compatibility_user = client.post(
            "/api/uploads/embodiment-image?kind=preview",
            files={"file": ("preview.png", png_bytes, "image/png")},
        )
        assert compatibility_user.status_code == 404

        try:
            server.load_config = lambda: {
                "self_use": {
                    "enabled": True,
                    "username": "avatar-user",
                    "require_localhost": False,
                }
            }
            blocked_avatar = client.post(
                "/api/uploads/avatar",
                files={"file": ("avatar.png", png_bytes, "image/png")},
            )
            assert blocked_avatar.status_code == 404

            blocked_generation = client.post(
                "/api/personas/999/avatar/generate",
                json={"desired_image": "legacy avatar request"},
            )
            assert blocked_generation.status_code == 404

            preview = client.post(
                "/api/uploads/embodiment-image?kind=preview",
                files={"file": ("preview.png", png_bytes, "image/png")},
            )
            assert preview.status_code == 200
            preview_payload = preview.json()
            assert preview_payload["kind"] == "preview"
            assert preview_payload["url"].startswith(f"/uploads/{user_id}/embodiment/preview/")
            preview_path = server.UPLOAD_DIR / str(user_id) / "embodiment" / "preview" / Path(preview_payload["url"]).name
            assert preview_path.read_bytes() == png_bytes

            fallback = client.post(
                "/api/uploads/embodiment-image?kind=fallback",
                files={"file": ("fallback.png", png_bytes, "image/png")},
            )
            assert fallback.status_code == 200
            assert fallback.json()["url"].startswith(f"/uploads/{user_id}/embodiment/fallback/")

            invalid_kind = client.post(
                "/api/uploads/embodiment-image?kind=avatar",
                files={"file": ("avatar.png", png_bytes, "image/png")},
            )
            assert invalid_kind.status_code == 400

            spoofed_preview = client.post(
                "/api/uploads/embodiment-image?kind=preview",
                files={"file": ("fake.png", b"not really an image", "image/png")},
            )
            assert spoofed_preview.status_code == 400
        finally:
            server.load_config = original_load_config

    print("Avatar upload verification passed")


if __name__ == "__main__":
    main()
