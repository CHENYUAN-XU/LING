"""Clean up only child processes created by a verification script."""
from __future__ import annotations

import os
import subprocess


def stop_test_process(process: subprocess.Popen, timeout: float = 8) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        # Windows venv python.exe may be a redirector with a real interpreter
        # child. Terminating just the redirector leaks the server and log handle.
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False, timeout=timeout,
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
