from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNNER = PROJECT_ROOT / "scripts" / "run_local_server.py"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(port: int, process: subprocess.Popen[str], timeout: float = 15) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=2)
            raise AssertionError(f"managed server exited early: {process.returncode}\n{stdout}\n{stderr}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            time.sleep(0.1)
    raise AssertionError("managed server did not become healthy")


def verify_runner_lifecycle() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        state_file = root / "server.json"
        stop_file = root / "server.stop"
        log_file = root / "server.log"
        shutdown_marker = root / "shutdown.txt"
        app_module = root / "launcher_test_app.py"
        app_module.write_text(
            """
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app):
    yield
    Path(os.environ["LING_LAUNCHER_SHUTDOWN_MARKER"]).write_text("stopped", encoding="utf-8")

app = FastAPI(lifespan=lifespan)

@app.get("/api/health")
def health():
    return {"ok": True, "database": "sqlite"}
""".strip(),
            encoding="utf-8",
        )
        port = _free_port()
        env = dict(os.environ)
        env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
        env["LING_LAUNCHER_SHUTDOWN_MARKER"] = str(shutdown_marker)
        process = subprocess.Popen(
            [
                sys.executable,
                str(RUNNER),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--app",
                "launcher_test_app:app",
                "--state-file",
                str(state_file),
                "--stop-file",
                str(stop_file),
                "--log-file",
                str(log_file),
            ],
            cwd=PROJECT_ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            health = _wait_for_health(port, process)
            assert health["ok"] is True
            state = json.loads(state_file.read_text(encoding="utf-8"))
            assert int(state["pid"]) == process.pid
            assert int(state["port"]) == port

            stop_file.write_text("stop", encoding="ascii")
            process.wait(timeout=15)
            assert process.returncode == 0
            assert shutdown_marker.read_text(encoding="utf-8") == "stopped"
            assert not state_file.exists()
            assert not stop_file.exists()
            assert "Application shutdown complete" in log_file.read_text(encoding="utf-8")
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


def verify_powershell_entrypoints() -> None:
    if os.name != "nt":
        return
    start_script = (PROJECT_ROOT / "scripts" / "start_local_server.ps1").read_text(encoding="utf-8")
    stop_script = (PROJECT_ROOT / "scripts" / "stop_local_server.ps1").read_text(encoding="utf-8")
    assert "Get-Content -LiteralPath $StateFile -Raw -Encoding UTF8" in stop_script
    assert "run_local_server.py" in start_script
    port = _free_port()
    start = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PROJECT_ROOT / "scripts" / "start_local_server.ps1"),
            "-Port",
            str(port),
            "-Python",
            sys.executable,
            "-SkipPreflight",
            "-DryRun",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert start.returncode == 0, start.stdout + start.stderr
    assert "dry run passed" in start.stdout
    assert str(port) in start.stdout

    stop = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PROJECT_ROOT / "scripts" / "stop_local_server.ps1"),
            "-Port",
            str(port),
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert stop.returncode == 0, stop.stdout + stop.stderr
    assert "not running" in stop.stdout


def main() -> None:
    verify_runner_lifecycle()
    verify_powershell_entrypoints()
    print("Local managed launcher verification passed")


if __name__ == "__main__":
    main()
