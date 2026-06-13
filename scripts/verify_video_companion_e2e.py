from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request_json(
    method: str,
    url: str,
    payload: dict | None = None,
    timeout: float = 5.0,
    headers: dict[str, str] | None = None,
) -> dict:
    data = None
    request_headers = {"Accept": "application/json"}
    request_headers.update(headers or {})
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8")) if raw else {}


def wait_for_json(url: str, timeout_seconds: float = 20.0) -> dict:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            return request_json("GET", url, timeout=2.0)
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def seed_user_and_persona(database_module) -> tuple[int, int]:
    ts = database_module.now_ts()
    with database_module.get_db() as db:
        user_id = int(
            db.execute(
                "INSERT INTO users (username, password_hash, created_at, updated_at) VALUES ('video-e2e', 'x', ?, ?)",
                (ts, ts),
            ).lastrowid
        )
        db.execute(
            "INSERT INTO user_profiles (user_id, nickname, created_at, updated_at) VALUES (?, 'video_e2e', ?, ?)",
            (user_id, ts, ts),
        )
        persona_id = int(
            db.execute(
                """
                INSERT INTO personas (
                    user_id, name, summary, prompt, relationship, speaking_style,
                    boundaries_json, created_at, updated_at
                )
                VALUES (?, 'Mio E2E', 'Video bridge test persona.', 'Speak naturally.', 'friend', 'short', ?, ?, ?)
                """,
                (user_id, '["do not invent camera facts"]', ts, ts),
            ).lastrowid
        )
    return user_id, persona_id


def default_video_path() -> Path:
    visual_dir = "".join((chr(0x89C6), chr(0x89C9)))
    return PROJECT_ROOT.parent / visual_dir / "video-companion"


def main() -> None:
    video_path = Path(os.environ.get("VIDEO_COMPANION_PATH") or default_video_path())
    if not video_path.exists():
        raise SystemExit(f"Video Companion path not found: {video_path}")

    main_port = free_port()
    video_port = free_port()
    token = "video-e2e-token"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = tmp_path / "mnemosyne_video_e2e.db"
        video_config = tmp_path / "video-companion.e2e.yaml"
        video_log = tmp_path / "video-companion.e2e.log"
        video_config.write_text(
            f"""
server:
  host: "127.0.0.1"
  port: {video_port}
  cors_origins:
    - "http://127.0.0.1:{main_port}"

privacy:
  defaults:
    camera: false
    microphone: false
    external_vision: false
    save_summary: false
    save_observation: false
  save_raw_media: false
  log_redact_pii: true

legacy_bridge:
  enabled: true
  api_base: "http://127.0.0.1:{main_port}"
  api_key_env: "MNEMOSYNE_API_KEY"
  timeout: 5
  retries: 1
""".strip(),
            encoding="utf-8",
        )

        import app.database as database

        database.DB_PATH = db_path
        os.environ["MNEMOSYNE_API_KEY"] = token
        os.environ["MNEMOSYNE_VIDEO_COMPANION_ENABLED"] = "true"
        os.environ["MNEMOSYNE_VIDEO_COMPANION_BASE_URL"] = f"http://127.0.0.1:{video_port}"
        os.environ["MNEMOSYNE_VIDEO_COMPANION_WS_URL"] = f"ws://127.0.0.1:{video_port}/ws"
        os.environ["MNEMOSYNE_VIDEO_COMPANION_PROJECT_PATH"] = str(video_path)

        import uvicorn
        import app.server as main_server

        user_id, persona_id = seed_user_and_persona(database)

        uvicorn_config = uvicorn.Config(
            main_server.app,
            host="127.0.0.1",
            port=main_port,
            log_level="warning",
            lifespan="off",
        )
        uvicorn_server = uvicorn.Server(uvicorn_config)
        main_thread = threading.Thread(target=uvicorn_server.run, daemon=True)
        main_thread.start()

        video_env = os.environ.copy()
        video_env["VC_CONFIG"] = str(video_config)
        video_env["MNEMOSYNE_API_KEY"] = token
        video_log_handle = video_log.open("w", encoding="utf-8", errors="replace")
        video_proc = subprocess.Popen(
            [sys.executable, "-m", "app.server"],
            cwd=video_path,
            env=video_env,
            stdout=video_log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )

        try:
            main_health = wait_for_json(f"http://127.0.0.1:{main_port}/api/health")
            assert main_health["ok"] is True

            video_health = wait_for_json(f"http://127.0.0.1:{video_port}/api/health")
            assert video_health["status"] == "ok"

            consent = request_json("GET", f"http://127.0.0.1:{video_port}/api/consent")
            assert consent["save_summary"] is False

            grant_summary = request_json(
                "POST",
                f"http://127.0.0.1:{video_port}/api/consent/save_summary/grant",
            )
            assert grant_summary["status"] == "granted"
            assert grant_summary["item"] == "save_summary"

            context = request_json(
                "GET",
                f"http://127.0.0.1:{main_port}/api/video/session-context?persona_id={persona_id}",
                timeout=5,
                headers={"Authorization": f"Bearer {token}"},
            )
            assert context["persona_id"] == str(persona_id)
            assert context["persona_name"] == "Mio E2E"

            start = request_json(
                "POST",
                f"http://127.0.0.1:{video_port}/api/session/start?persona_id={persona_id}",
            )
            assert start["status"] == "started"
            assert start["persona_id"] == str(persona_id)

            stop = request_json("POST", f"http://127.0.0.1:{video_port}/api/session/stop", timeout=20)
            assert stop["status"] == "stopped"
            assert stop["summary"]["persona_id"] == str(persona_id)
            assert stop["summary"]["summary_text"]
            assert stop["consent"]["save_summary"] is True

            with database.get_db() as db:
                saved = db.execute(
                    """
                    SELECT conversations.id, conversations.summary, messages.content
                    FROM conversations
                    JOIN messages ON messages.conversation_id = conversations.id
                    WHERE conversations.user_id = ?
                      AND conversations.persona_id = ?
                      AND conversations.title LIKE '视频会话摘要%'
                      AND messages.role = 'assistant'
                    ORDER BY conversations.id DESC
                    LIMIT 1
                    """,
                    (user_id, persona_id),
                ).fetchone()
                observation_count = int(
                    db.execute(
                        """
                        SELECT COUNT(*) AS c
                        FROM world_observations
                        WHERE user_id = ? AND source = 'video_companion' AND observation_type = 'session_summary'
                        """,
                        (user_id,),
                    ).fetchone()["c"]
                )
            assert saved is not None
            assert saved["summary"]
            assert saved["content"]
            assert observation_count == 1

            print("Video Companion end-to-end verification passed")
        except Exception:
            if video_log.exists():
                print("\n--- Video Companion log tail ---")
                print(video_log.read_text(encoding="utf-8", errors="replace")[-6000:])
            raise
        finally:
            uvicorn_server.should_exit = True
            video_proc.terminate()
            try:
                video_proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                video_proc.kill()
                video_proc.wait(timeout=5)
            video_log_handle.close()


if __name__ == "__main__":
    main()
