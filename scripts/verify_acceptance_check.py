from __future__ import annotations

import sqlite3
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.acceptance_check import _llm_route_fingerprint, acceptance_report
from app.manual_acceptance import load_manual_acceptance, record_manual_acceptance, revoke_manual_acceptance


def _config(root: Path) -> dict:
    return {
        "self_use": {
            "enabled": True,
            "require_localhost": True,
            "username": "owner",
            "chat_enabled": True,
        },
        "llm_routes": {
            "default": {},
            "chat": {
                "provider": "test",
                "model": "ling-test",
                "base_url": "http://127.0.0.1:9999/v1",
                "api_key_env": "LING_TEST_KEY",
            },
        },
        "live2d": {"enabled": True, "vts_ws_url": "ws://127.0.0.1:8002"},
        "voice": {"enabled": True, "tts_provider": "openai_tts", "api_key_env": "VOICE_TEST_KEY"},
        "video_companion": {"enabled": False, "project_path": str(root / "video")},
        "screen": {"enabled": False},
        "proactive": {"enabled": False},
    }


def _database(path: Path) -> None:
    route_key = _llm_route_fingerprint(
        "test", "ling-test", "http://127.0.0.1:9999/v1", "LING_TEST_KEY", "present"
    )
    with closing(sqlite3.connect(path)) as db:
        db.executescript(
            """
            CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, status TEXT);
            CREATE TABLE personas (
                id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, prompt TEXT,
                live2d_model_id TEXT, live2d_preview_url TEXT,
                fallback_image_url TEXT, voice_profile TEXT, status TEXT
            );
            CREATE TABLE self_use_companion_bindings (user_id INTEGER PRIMARY KEY, persona_id INTEGER);
            CREATE TABLE user_consents (user_id INTEGER, consent_key TEXT, granted INTEGER);
            CREATE TABLE llm_route_verifications (
                route_key TEXT, provider TEXT, model TEXT, base_url TEXT, state TEXT, checked_at INTEGER
            );
            INSERT INTO users VALUES (1, 'owner', 'active');
            INSERT INTO personas VALUES (
                7, 1, 'Mio',
                'LING 本地工作区中唯一、持续存在的 AI companion',
                'mio-main', '', '', 'mio-voice', 'active'
            );
            INSERT INTO self_use_companion_bindings VALUES (1, 7);
            """
        )
        db.execute(
            "INSERT INTO llm_route_verifications VALUES (?, ?, ?, ?, 'verified', ?)",
            (route_key, "test", "ling-test", "http://127.0.0.1:9999/v1", int(time.time())),
        )
        db.commit()


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        db_path = root / "app.db"
        _database(db_path)
        for relative in (
            "scripts/start_local_server.ps1",
            "scripts/stop_local_server.ps1",
            "scripts/run_local_server.py",
        ):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# verify\n", encoding="utf-8")

        config = _config(root)
        report = acceptance_report(
            config,
            db_path=db_path,
            environ={"LING_TEST_KEY": "present", "VOICE_TEST_KEY": "present"},
            probe_local_ports=False,
            base_dir=root,
        )
        by_key = {item["key"]: item for item in report["checks"]}
        assert report["network_calls"] is False
        assert report["automated_ready"] is True
        assert report["fully_accepted"] is False
        assert by_key["single_companion_binding"]["status"] == "ready"
        assert by_key["single_companion_binding"]["evidence"]["persona_id"] == 7
        assert "name" not in by_key["single_companion_binding"]["evidence"]
        assert by_key["ling_identity_prompt"]["status"] == "ready"
        assert by_key["chat_model"]["status"] == "manual"
        assert by_key["live2d"]["status"] == "manual"
        assert by_key["voice"]["status"] == "manual"
        assert by_key["video_companion"]["status"] == "optional"
        assert by_key["daily_endurance"]["status"] == "manual"

        changed_key = acceptance_report(
            config,
            db_path=db_path,
            environ={"LING_TEST_KEY": "changed", "VOICE_TEST_KEY": "present"},
            probe_local_ports=False,
            base_dir=root,
        )
        changed_key_chat = next(item for item in changed_key["checks"] if item["key"] == "chat_model")
        assert changed_key_chat["status"] == "pending"
        assert "explicit local probe" in changed_key_chat["detail"]

        ledger_path = root / "data" / "acceptance" / "manual_acceptance.json"
        for key in ("chat_model", "live2d", "voice", "daily_endurance"):
            receipt = record_manual_acceptance(report["checks"], ledger_path, key, f"verified real {key} behavior")
            assert receipt["check"] == key
            assert len(receipt["fingerprint"]) == 64
        accepted_report = acceptance_report(
            config,
            db_path=db_path,
            environ={"LING_TEST_KEY": "present", "VOICE_TEST_KEY": "present"},
            probe_local_ports=False,
            base_dir=root,
        )
        accepted_by_key = {item["key"]: item for item in accepted_report["checks"]}
        assert accepted_report["automated_ready"] is True
        assert accepted_report["fully_accepted"] is True
        assert set(accepted_report["manual_acceptance"]["accepted"]) == {
            "chat_model", "daily_endurance", "live2d", "voice"
        }
        assert accepted_by_key["voice"]["evidence"]["manual_acceptance"]["current"] is True

        config["voice"]["tts_provider"] = "edge"
        config["self_use"]["chat_enabled"] = False
        pending = acceptance_report(
            config,
            db_path=db_path,
            environ={"LING_TEST_KEY": "present", "VOICE_TEST_KEY": "present"},
            probe_local_ports=False,
            base_dir=root,
        )
        pending_by_key = {item["key"]: item for item in pending["checks"]}
        assert pending["automated_ready"] is False
        assert pending_by_key["chat_model"]["status"] == "pending"
        assert pending_by_key["voice"]["status"] == "pending"
        assert "Edge TTS" in pending_by_key["voice"]["detail"]
        assert {"chat_model", "voice"} <= set(pending["manual_acceptance"]["stale"])

        try:
            record_manual_acceptance(pending["checks"], ledger_path, "voice", "tested")
        except ValueError as exc:
            assert "automated prerequisites" in str(exc)
        else:
            raise AssertionError("pending checks must not be manually accepted")

        assert revoke_manual_acceptance(ledger_path, "voice") is True
        assert revoke_manual_acceptance(ledger_path, "voice") is False
        assert "voice" not in load_manual_acceptance(ledger_path)["receipts"]

    print("LING acceptance check verification passed")


if __name__ == "__main__":
    main()
