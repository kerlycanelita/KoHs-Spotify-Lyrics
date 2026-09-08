from __future__ import annotations

import csv
import ctypes
import io
import locale
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
EXPECTED_PYTHON = Path(sys.executable).resolve()
EXPECTED_BASE_PYTHON = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
EXPECTED_CLOUDFLARED = (BASE_DIR / "tools" / "cloudflared.exe").resolve()
EXPECTED_APP = (BASE_DIR / "app.py").resolve()
RUNTIME_DIR = BASE_DIR / "runtime"
URL_FILE = BASE_DIR / "tiktok-url.txt"
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001
SYNCHRONIZE = 0x00100000
WAIT_TIMEOUT_MS = 5000

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel32.TerminateProcess.restype = wintypes.BOOL
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL


def process_path(pid: int) -> Path | None:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return Path(buffer.value).resolve()
    finally:
        kernel32.CloseHandle(handle)


def terminate_verified_process(pid: int, expected_path: Path, label: str) -> bool:
    actual_path = process_path(pid)
    if actual_path is None or actual_path != expected_path:
        return False
    handle = kernel32.OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, False, pid)
    if not handle:
        return False
    try:
        if not kernel32.TerminateProcess(handle, 0):
            return False
        kernel32.WaitForSingleObject(handle, WAIT_TIMEOUT_MS)
        print(f"[APAGADO] {label} (PID {pid})")
        return True
    finally:
        kernel32.CloseHandle(handle)


def process_command_line(pid: int) -> str:
    command = (
        f"Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}' "
        "| Select-Object -ExpandProperty CommandLine"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding=locale.getpreferredencoding(False),
        errors="replace",
        check=False,
    )
    return result.stdout.strip()


def process_parent_pid(pid: int) -> int | None:
    command = (
        f"Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}' "
        "| Select-Object -ExpandProperty ParentProcessId"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding=locale.getpreferredencoding(False),
        errors="replace",
        check=False,
    )
    value = result.stdout.strip()
    return int(value) if value.isdigit() else None


def child_pids(parent_pid: int) -> set[int]:
    command = (
        f"Get-CimInstance Win32_Process -Filter 'ParentProcessId = {parent_pid}' "
        "| Select-Object -ExpandProperty ProcessId"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding=locale.getpreferredencoding(False),
        errors="replace",
        check=False,
    )
    return {int(line.strip()) for line in result.stdout.splitlines() if line.strip().isdigit()}


def command_runs_expected_app(command_line: str) -> bool:
    return str(EXPECTED_APP).casefold() in command_line.casefold()


def command_runs_tunnel_launcher(command_line: str) -> bool:
    return "tunnel_launcher.py" in command_line.casefold()


def terminate_tunnel_launcher(pid: int, *, trusted_recorded_pid: bool = False) -> bool:
    actual_path = process_path(pid)
    command_line = process_command_line(pid)
    if not command_runs_tunnel_launcher(command_line) and not trusted_recorded_pid:
        return False

    if actual_path == EXPECTED_PYTHON:
        stopped = False
        for child_pid in child_pids(pid):
            if (
                process_path(child_pid) == EXPECTED_BASE_PYTHON
                and command_runs_tunnel_launcher(process_command_line(child_pid))
            ):
                stopped |= terminate_verified_process(
                    child_pid, EXPECTED_BASE_PYTHON, "Supervisor del túnel"
                )
        stopped |= terminate_verified_process(
            pid, EXPECTED_PYTHON, "Lanzador del supervisor"
        )
        return stopped

    if actual_path != EXPECTED_BASE_PYTHON:
        return False
    stopped = terminate_verified_process(
        pid, EXPECTED_BASE_PYTHON, "Supervisor del túnel"
    )
    parent_pid = process_parent_pid(pid)
    if (
        parent_pid is not None
        and process_path(parent_pid) == EXPECTED_PYTHON
        and command_runs_tunnel_launcher(process_command_line(parent_pid))
    ):
        stopped |= terminate_verified_process(
            parent_pid, EXPECTED_PYTHON, "Lanzador del supervisor"
        )
    return stopped


def terminate_server(pid: int, *, trusted_recorded_pid: bool = False) -> bool:
    actual_path = process_path(pid)
    command_line = process_command_line(pid)
    listening_pids = listening_server_pids()

    if actual_path == EXPECTED_PYTHON and (
        command_runs_expected_app(command_line) or trusted_recorded_pid
    ):
        stopped = False
        for child_pid in child_pids(pid):
            if process_path(child_pid) == EXPECTED_BASE_PYTHON and (
                command_runs_expected_app(process_command_line(child_pid))
                or child_pid in listening_pids
            ):
                stopped |= terminate_verified_process(child_pid, EXPECTED_BASE_PYTHON, "Servidor local")
        stopped |= terminate_verified_process(pid, EXPECTED_PYTHON, "Lanzador del servidor")
        return stopped

    if actual_path != EXPECTED_BASE_PYTHON or not (
        command_runs_expected_app(command_line)
        or (trusted_recorded_pid and pid in listening_pids)
    ):
        return False
    parent_pid = process_parent_pid(pid)
    if parent_pid is None or process_path(parent_pid) != EXPECTED_PYTHON:
        return False
    if not command_runs_expected_app(process_command_line(parent_pid)):
        return False
    return terminate_verified_process(pid, EXPECTED_BASE_PYTHON, "Servidor local")


def listening_server_pids() -> set[int]:
    command = (
        "Get-NetTCPConnection -State Listen -LocalPort 3000,3443 "
        "-ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding=locale.getpreferredencoding(False),
        errors="replace",
        check=False,
    )
    return {int(line.strip()) for line in result.stdout.splitlines() if line.strip().isdigit()}


def cloudflared_pids() -> set[int]:
    result = subprocess.run(
        ["tasklist.exe", "/FI", "IMAGENAME eq cloudflared.exe", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        encoding=locale.getpreferredencoding(False),
        errors="replace",
        check=False,
    )
    pids: set[int] = set()
    for row in csv.reader(io.StringIO(result.stdout)):
        if len(row) >= 2 and row[0].lower() == "cloudflared.exe":
            try:
                pids.add(int(row[1]))
            except ValueError:
                pass
    return pids


def recorded_pid(filename: str) -> int | None:
    path = RUNTIME_DIR / filename
    try:
        value = path.read_text(encoding="ascii").strip()
        return int(value) if value.isdigit() else None
    except OSError:
        return None


def remove_runtime_pid(filename: str, pid: int | None) -> None:
    if pid is None:
        return
    path = RUNTIME_DIR / filename
    try:
        if path.read_text(encoding="ascii").strip() == str(pid):
            path.unlink()
    except OSError:
        pass


def main() -> int:
    stopped = 0
    launcher_pid = recorded_pid("launcher.pid")
    tunnel_pid = recorded_pid("tunnel.pid")
    server_pid = recorded_pid("server.pid")
    if launcher_pid is not None:
        stopped += terminate_tunnel_launcher(
            launcher_pid, trusted_recorded_pid=True
        )
    tunnel_candidates = cloudflared_pids()
    if tunnel_pid is not None:
        tunnel_candidates.add(tunnel_pid)
    for pid in tunnel_candidates:
        stopped += terminate_verified_process(pid, EXPECTED_CLOUDFLARED, "Túnel público")
    server_candidates = listening_server_pids()
    if server_pid is not None:
        server_candidates.add(server_pid)
    for pid in server_candidates:
        stopped += terminate_server(
            pid, trusted_recorded_pid=pid == server_pid
        )

    remove_runtime_pid("launcher.pid", launcher_pid)
    remove_runtime_pid("tunnel.pid", tunnel_pid)
    remove_runtime_pid("server.pid", server_pid)
    try:
        URL_FILE.unlink(missing_ok=True)
    except OSError:
        pass

    if stopped:
        print(f"\nListo: {stopped} servicio(s) de KoH's Spotify Lyrics detenido(s).")
    else:
        print("No había servicios de KoH's Spotify Lyrics ejecutándose.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
