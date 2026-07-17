from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from .config import load_config


DEFAULT_EASYVTUBER_CONFIG: dict[str, Any] = {
    "enabled": False,
    "root": r"E:\EasyVtuber_v0.8.0\EasyVtuber",
}


class EasyVtuberError(RuntimeError):
    pass


def load_easyvtuber_config() -> dict[str, Any]:
    raw = load_config().get("easyvtuber", {})
    if not isinstance(raw, dict):
        raw = {}
    config = dict(DEFAULT_EASYVTUBER_CONFIG)
    config.update(raw)
    root_override = os.environ.get("LING_EASYVTUBER_ROOT")
    if root_override and root_override.strip():
        config["root"] = root_override.strip()
    config["enabled"] = bool(config.get("enabled", False))
    config["root"] = str(config.get("root") or DEFAULT_EASYVTUBER_CONFIG["root"])
    return config


def easyvtuber_status() -> dict[str, Any]:
    config = load_easyvtuber_config()
    root = Path(config["root"]).expanduser()
    launcher = _official_launcher(root)
    processes = _running_launcher_processes(root)
    return {
        "enabled": bool(config["enabled"]),
        "root": str(root),
        "root_exists": root.is_dir(),
        "launcher_exists": launcher is not None,
        "running": bool(processes),
        "process_ids": [item["pid"] for item in processes],
    }


def open_easyvtuber() -> dict[str, Any]:
    config = load_easyvtuber_config()
    if not config["enabled"]:
        raise EasyVtuberError("EasyVtuber is disabled in config.yaml")
    if os.name != "nt":
        raise EasyVtuberError("EasyVtuber can only be opened from Windows")

    root = Path(config["root"]).expanduser()
    launcher = _official_launcher(root)
    if launcher is None:
        raise EasyVtuberError("EasyVtuber official launcher was not found under the configured root")

    processes = _running_launcher_processes(root)
    if processes:
        return {"opened": False, "already_running": True, "status": easyvtuber_status()}

    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    subprocess.Popen(
        ["cmd.exe", "/d", "/s", "/c", str(launcher)],
        cwd=str(root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )
    return {"opened": True, "already_running": False, "status": easyvtuber_status()}


def _official_launcher(root: Path) -> Path | None:
    if not root.is_dir():
        return None
    # The official release uses a localized filename. Select its stable 01A prefix
    # instead of hard-coding a locale-dependent filename.
    candidates = sorted(root.glob("01A.*.bat"))
    return candidates[0] if candidates else None


def _running_launcher_processes(root: Path) -> list[dict[str, Any]]:
    if os.name != "nt" or not root.is_dir():
        return []
    # QueryFullProcessImageNameW works for the current desktop user without the
    # administrator-only WMI/CIM permission required on some Windows installs.
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    th32cs_snapprocess = 0x00000002
    invalid_handle_value = ctypes.c_void_p(-1).value
    max_path = 32768

    class ProcessEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_snapshot = kernel32.CreateToolhelp32Snapshot
    create_snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    create_snapshot.restype = wintypes.HANDLE
    process_first = kernel32.Process32FirstW
    process_first.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W)]
    process_first.restype = wintypes.BOOL
    process_next = kernel32.Process32NextW
    process_next.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W)]
    process_next.restype = wintypes.BOOL
    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    query_image = kernel32.QueryFullProcessImageNameW
    query_image.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    query_image.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    target_executable = str((root / "envs" / "python_embedded" / "pythonw.exe").resolve()).casefold()
    target_console_executable = str((root / "envs" / "python_embedded" / "python.exe").resolve()).casefold()
    found: list[dict[str, Any]] = []
    snapshot = create_snapshot(th32cs_snapprocess, 0)
    if snapshot == invalid_handle_value:
        return found
    try:
        entry = ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(ProcessEntry32W)
        has_entry = bool(process_first(snapshot, ctypes.byref(entry)))
        while has_entry:
            exe_name = str(entry.szExeFile).casefold()
            if exe_name in {"python.exe", "pythonw.exe"}:
                handle = open_process(process_query_limited_information, False, entry.th32ProcessID)
                if handle:
                    try:
                        buffer = ctypes.create_unicode_buffer(max_path)
                        size = wintypes.DWORD(max_path)
                        if query_image(handle, 0, buffer, ctypes.byref(size)):
                            executable = str(buffer.value).casefold()
                            if executable in {target_executable, target_console_executable}:
                                found.append({"pid": int(entry.th32ProcessID)})
                    finally:
                        close_handle(handle)
            has_entry = bool(process_next(snapshot, ctypes.byref(entry)))
    finally:
        close_handle(snapshot)
    return found
