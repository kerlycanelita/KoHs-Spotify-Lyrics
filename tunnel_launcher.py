from __future__ import annotations

import queue
import re
import json
import msvcrt
import os
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from urllib.parse import quote, urlsplit


BASE_DIR = Path(__file__).resolve().parent
CLOUDFLARED = BASE_DIR / "tools" / "cloudflared.exe"
LOCAL_BASE_URL = (
    os.environ.get("KOHS_LOCAL_BASE_URL", "").strip()
    or ("http://localhost:3000" if os.environ.get("KOHS_HTTP_ONLY") == "1" else "https://localhost:3443")
)
TUNNEL_URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.IGNORECASE)
SERVER_LOG = BASE_DIR / "logs" / "server.log"
TUNNEL_LOG = BASE_DIR / "logs" / "tunnel.log"
URL_FILE = BASE_DIR / "tiktok-url.txt"
RUNTIME_DIR = BASE_DIR / "runtime"
SERVER_PID_FILE = RUNTIME_DIR / "server.pid"
TUNNEL_PID_FILE = RUNTIME_DIR / "tunnel.pid"
LAUNCHER_PID_FILE = RUNTIME_DIR / "launcher.pid"
LAUNCHER_LOCK_FILE = RUNTIME_DIR / "launcher.lock"


def request_ok(url: str, *, verify_tls: bool = True, timeout: float = 5.0) -> bool:
    context = None if verify_tls else ssl._create_unverified_context()
    request = urllib.request.Request(url, headers={"User-Agent": "KoHsSpotifyLyrics/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            return 200 <= response.status < 400
    except (OSError, urllib.error.URLError):
        return False


def wait_until_ready(url: str, *, verify_tls: bool, seconds: int) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if request_ok(url, verify_tls=verify_tls):
            return True
        time.sleep(0.5)
    return False


def cloudflare_ipv4_addresses(hostname: str) -> list[str]:
    query_url = f"https://cloudflare-dns.com/dns-query?name={quote(hostname)}&type=A"
    request = urllib.request.Request(
        query_url,
        headers={"Accept": "application/dns-json", "User-Agent": "KoHsSpotifyLyrics/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=6) as response:
            payload = json.load(response)
    except (OSError, ValueError, urllib.error.URLError):
        return []
    return [
        answer["data"]
        for answer in payload.get("Answer", [])
        if answer.get("type") == 1 and isinstance(answer.get("data"), str)
    ]


def request_ok_at_address(url: str, address: str, timeout: float = 8.0) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    path = parsed.path or "/"
    if parsed.query:
        path += f"?{parsed.query}"
    context = ssl.create_default_context()
    try:
        with socket.create_connection((address, parsed.port or 443), timeout=timeout) as raw_socket:
            with context.wrap_socket(raw_socket, server_hostname=parsed.hostname) as secure_socket:
                request = (
                    f"GET {path} HTTP/1.1\r\n"
                    f"Host: {parsed.hostname}\r\n"
                    "User-Agent: KoHsSpotifyLyrics/1.0\r\n"
                    "Connection: close\r\n\r\n"
                )
                secure_socket.sendall(request.encode("ascii"))
                status_line = secure_socket.recv(128).split(b"\r\n", 1)[0]
                match = re.match(rb"HTTP/\d(?:\.\d)?\s+(\d{3})", status_line)
                return bool(match and 200 <= int(match.group(1)) < 400)
    except (OSError, ssl.SSLError):
        return False


def wait_for_public_overlay(url: str, seconds: int = 45) -> bool:
    """Wait briefly for a brand-new Quick Tunnel to become reachable.

    Prefer the machine's normal DNS path because some networks block or delay
    cloudflare-dns.com even while trycloudflare.com itself works.  The manual
    Cloudflare DNS path remains only as a fallback.
    """
    hostname = urlsplit(url).hostname
    if not hostname:
        return False

    deadline = time.monotonic() + seconds
    last_doh_attempt = 0.0
    while time.monotonic() < deadline:
        if request_ok(url, verify_tls=True, timeout=6):
            return True

        now = time.monotonic()
        if now - last_doh_attempt >= 8:
            last_doh_attempt = now
            for address in cloudflare_ipv4_addresses(hostname):
                if request_ok_at_address(url, address):
                    return True

        time.sleep(1)
    return False


def start_local_server() -> tuple[subprocess.Popen[bytes] | None, object | None]:
    if request_ok(f"{LOCAL_BASE_URL}/api/health", verify_tls=False, timeout=2):
        return None, None

    (BASE_DIR / "logs").mkdir(exist_ok=True)
    log_handle = SERVER_LOG.open("ab")
    process = subprocess.Popen(
        [sys.executable, str(BASE_DIR / "app.py")],
        cwd=BASE_DIR,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    RUNTIME_DIR.mkdir(exist_ok=True)
    SERVER_PID_FILE.write_text(str(process.pid), encoding="ascii")
    if not wait_until_ready(f"{LOCAL_BASE_URL}/api/health", verify_tls=False, seconds=25):
        process.terminate()
        log_handle.close()
        raise RuntimeError(f"El servidor local no inició. Revisa {SERVER_LOG}")
    return process, log_handle


def stream_output_with_log(
    process: subprocess.Popen[str], output: queue.Queue[str | None]
) -> None:
    assert process.stdout is not None
    TUNNEL_LOG.parent.mkdir(exist_ok=True)
    with TUNNEL_LOG.open("a", encoding="utf-8", errors="replace") as log:
        for line in process.stdout:
            clean = line.rstrip()
            log.write(clean + "\n")
            log.flush()
            output.put(clean)
    output.put(None)


def copy_to_clipboard(text: str) -> None:
    subprocess.run(["clip.exe"], input=text, text=True, check=True)


def stop_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def remove_pid_file(path: Path, process: subprocess.Popen | None) -> None:
    if process is None or not path.exists():
        return
    try:
        if path.read_text(encoding="ascii").strip() == str(process.pid):
            path.unlink()
    except OSError:
        pass


def acquire_launcher_lock() -> object | None:
    RUNTIME_DIR.mkdir(exist_ok=True)
    handle = LAUNCHER_LOCK_FILE.open("a+b")
    if handle.seek(0, 2) == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        return None
    return handle


def start_public_tunnel() -> tuple[subprocess.Popen[str], queue.Queue[str | None]]:
    command = [
        str(CLOUDFLARED),
        "tunnel",
        "--url",
        LOCAL_BASE_URL,
    ]
    if LOCAL_BASE_URL.lower().startswith("https://"):
        command.append("--no-tls-verify")
    command.extend(
        [
            "--http-host-header",
            "tunnel.local",
            "--no-autoupdate",
            "--loglevel",
            "info",
        ]
    )
    process = subprocess.Popen(
        command,
        cwd=BASE_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    TUNNEL_PID_FILE.write_text(str(process.pid), encoding="ascii")
    output: queue.Queue[str | None] = queue.Queue()
    threading.Thread(
        target=stream_output_with_log,
        args=(process, output),
        daemon=True,
    ).start()
    return process, output


def discover_public_url(
    process: subprocess.Popen[str], output: queue.Queue[str | None]
) -> str:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline and process.poll() is None:
        try:
            line = output.get(timeout=0.5)
        except queue.Empty:
            continue
        if line:
            match = TUNNEL_URL_PATTERN.search(line)
            if match:
                return f"{match.group(0).rstrip('/')}/overlay"
    raise RuntimeError(
        "Cloudflare no entregó una URL pública. Comprueba tu conexión a Internet."
    )


def save_public_url(overlay_url: str) -> None:
    temporary = URL_FILE.with_suffix(".tmp")
    temporary.write_text(overlay_url + "\n", encoding="utf-8")
    temporary.replace(URL_FILE)
    try:
        copy_to_clipboard(overlay_url)
    except (OSError, subprocess.SubprocessError):
        print("[AVISO] No se pudo copiar el enlace al portapapeles.")


def supervised_main() -> int:
    lock_handle = acquire_launcher_lock()
    if lock_handle is None:
        print("Los servicios ya están iniciados.")
        return 0
    if not CLOUDFLARED.exists():
        print(f"[ERROR] Falta {CLOUDFLARED}")
        lock_handle.close()
        return 1

    LAUNCHER_PID_FILE.write_text(str(os.getpid()), encoding="ascii")
    try:
        URL_FILE.unlink(missing_ok=True)
    except OSError:
        pass

    local_process: subprocess.Popen[bytes] | None = None
    local_log = None
    tunnel_process: subprocess.Popen[str] | None = None
    first_connection = True
    retry_delay = 2
    try:
        print("[3/4] Verificando servidor local...", flush=True)
        local_process, local_log = start_local_server()
        while True:
            try:
                print("[4/4] Creando enlace HTTPS público para TikTok...", flush=True)
                tunnel_process, output = start_public_tunnel()
                overlay_url = discover_public_url(tunnel_process, output)
                print(f"Dominio creado: {overlay_url.removesuffix('/overlay')}", flush=True)
                print("Esperando brevemente a que Cloudflare termine de activarlo...", flush=True)

                public_ready = wait_for_public_overlay(overlay_url, seconds=45)
                save_public_url(overlay_url)
                if public_ready:
                    print("Overlay público verificado correctamente.", flush=True)
                else:
                    print(
                        "[AVISO] Cloudflare entregó la URL, pero la comprobación pública local "
                        "todavía no responde. Se conservará el túnel porque algunos DNS tardan "
                        "en propagar; prueba el enlace de nuevo en unos segundos.",
                        flush=True,
                    )

                if first_connection and os.environ.get("KOHS_NO_BROWSER") != "1":
                    webbrowser.open(f"{LOCAL_BASE_URL}/config")
                    first_connection = False
                print("=" * 72, flush=True)
                print(" ENLACE PARA TIKTOK LIVE STUDIO", flush=True)
                print(f" {overlay_url}", flush=True)
                print("=" * 72, flush=True)
                retry_delay = 2

                while tunnel_process.poll() is None:
                    try:
                        line = output.get(timeout=1)
                    except queue.Empty:
                        continue
                    if line is None:
                        break
                    if " ERR " in f" {line} " or " WRN " in f" {line} ":
                        print(line, flush=True)
                exit_code = tunnel_process.poll()
                raise RuntimeError(f"El túnel se detuvo con código {exit_code}.")
            except KeyboardInterrupt:
                return 0
            except Exception as error:
                print(f"[AVISO] {error}", flush=True)
            finally:
                stop_process(tunnel_process)
                remove_pid_file(TUNNEL_PID_FILE, tunnel_process)
                tunnel_process = None

            print(
                f"Reintentando Cloudflare en {retry_delay} segundos...",
                flush=True,
            )
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 30)
    finally:
        stop_process(tunnel_process)
        stop_process(local_process)
        remove_pid_file(TUNNEL_PID_FILE, tunnel_process)
        remove_pid_file(SERVER_PID_FILE, local_process)
        try:
            if LAUNCHER_PID_FILE.read_text(encoding="ascii").strip() == str(os.getpid()):
                LAUNCHER_PID_FILE.unlink()
        except OSError:
            pass
        if local_log is not None:
            local_log.close()
        lock_handle.close()


if __name__ == "__main__":
    raise SystemExit(supervised_main())
