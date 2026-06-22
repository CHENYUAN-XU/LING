from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

import uvicorn


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _write_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _remove_owned_state(path: Path, pid: int) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return
    if int(payload.get("pid") or 0) == pid:
        path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the managed local LING server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--app", default="app.server:app")
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--stop-file", type=Path, required=True)
    parser.add_argument("--log-file", type=Path)
    args = parser.parse_args()

    log_handle = None
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    if args.log_file:
        args.log_file.parent.mkdir(parents=True, exist_ok=True)
        log_handle = args.log_file.open("a", encoding="utf-8", buffering=1)
        sys.stdout = log_handle
        sys.stderr = log_handle

    pid = os.getpid()
    args.stop_file.parent.mkdir(parents=True, exist_ok=True)
    args.stop_file.unlink(missing_ok=True)
    _write_state(
        args.state_file,
        {
            "pid": pid,
            "host": args.host,
            "port": args.port,
            "app": args.app,
            "started_at": int(time.time()),
            "log_file": str(args.log_file) if args.log_file else "",
        },
    )

    server = uvicorn.Server(uvicorn.Config(args.app, host=args.host, port=args.port, log_level="info"))
    monitor_stop = threading.Event()

    def monitor_stop_request() -> None:
        while not monitor_stop.wait(0.25):
            if args.stop_file.exists():
                server.should_exit = True
                return

    monitor = threading.Thread(target=monitor_stop_request, name="ling-local-stop-monitor", daemon=True)
    monitor.start()
    try:
        server.run()
    finally:
        monitor_stop.set()
        monitor.join(timeout=1)
        args.stop_file.unlink(missing_ok=True)
        _remove_owned_state(args.state_file, pid)
        if log_handle:
            log_handle.flush()
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            log_handle.close()


if __name__ == "__main__":
    main()
