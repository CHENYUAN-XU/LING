from __future__ import annotations

import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app.database as database


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        database.DB_PATH = Path(tmp) / "ling-self-use-soak.db"
        database.init_db()

        import app.auth as auth
        import app.server as server

        user = auth.get_or_create_local_user("ling_soak_owner", "")
        persona = server._ensure_self_use_default_persona(
            int(user["id"]),
            {"seed_default_persona": True, "default_persona_name": "澪"},
        )
        assert persona is not None
        persona_id = int(persona["id"])

        original_load_config = server.load_config
        original_video_status = server.get_video_companion_status
        try:
            server.load_config = lambda: {
                "self_use": {
                    "enabled": True,
                    "username": "ling_soak_owner",
                    "require_localhost": True,
                    "chat_enabled": False,
                    "seed_default_persona": True,
                    "default_persona_name": "澪",
                }
            }
            server.get_video_companion_status = lambda: {
                "enabled": False,
                "connected": False,
                "reason": "video_companion_disabled",
                "config": {"enabled": False},
            }

            def read_status(iteration: int) -> None:
                for _ in range(30):
                    status = server.companion_status(user)
                    assert int(status["persona_id"]) == persona_id
                    assert status["self_use"]["enabled"] is True
                    assert status["self_use"]["chat_enabled"] is False
                    assert status["video_companion"]["connected"] is False

            def write_profile(worker: int) -> None:
                for iteration in range(30):
                    with database.get_db() as db:
                        db.execute(
                            "UPDATE user_profiles SET signature = ?, updated_at = ? WHERE user_id = ?",
                            (f"soak-{worker}-{iteration}", database.now_ts(), int(user["id"])),
                        )

            jobs = []
            with ThreadPoolExecutor(max_workers=8) as pool:
                for worker in range(4):
                    jobs.append(pool.submit(read_status, worker))
                    jobs.append(pool.submit(write_profile, worker))
                for job in as_completed(jobs):
                    job.result()

            with database.get_db() as db:
                binding = db.execute(
                    "SELECT persona_id FROM self_use_companion_bindings WHERE user_id = ?",
                    (int(user["id"]),),
                ).fetchone()
                assert binding is not None and int(binding["persona_id"]) == persona_id
                assert db.execute(
                    "SELECT COUNT(*) FROM personas WHERE user_id = ? AND status = 'active'",
                    (int(user["id"]),),
                ).fetchone()[0] == 1
                assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            server.load_config = original_load_config
            server.get_video_companion_status = original_video_status

    print("LING self-use soak verification passed")


if __name__ == "__main__":
    main()
