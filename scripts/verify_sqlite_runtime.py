from __future__ import annotations

import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app.database as database


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        database.DB_PATH = Path(tmp) / "runtime.db"
        database.init_db()

        with database.get_db() as db:
            assert int(db.execute("PRAGMA foreign_keys").fetchone()[0]) == 1
            assert int(db.execute("PRAGMA busy_timeout").fetchone()[0]) >= 1000
            journal_mode = str(db.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            assert journal_mode in {"wal", "delete"}

        status = database.sqlite_runtime_status()
        assert status["foreign_keys"] is True
        assert status["busy_timeout_ms"] >= 1000
        assert status["journal_mode"] in {"wal", "delete"}
        assert status["path"].endswith("runtime.db")

        import app.server as server

        health = server.health()
        assert health["database"] == "sqlite"
        assert health["sqlite"]["foreign_keys"] is True

    print("SQLite runtime verification passed")


if __name__ == "__main__":
    main()
