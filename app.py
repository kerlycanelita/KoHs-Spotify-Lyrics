from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from artwork import ArtworkProvider
from config_manager import ConfigManager
from font_assets import LocalFontCatalog
from lyrics import LyricsProvider
from models import OverlayConfig
from spotify_session import SpotifySessionReader, WINRT_AVAILABLE
from state_manager import PlaybackCoordinator, empty_state
from translation import TranslationProvider


BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "cache"
ARTWORK_DIR = CACHE_DIR / "artwork"
LYRICS_DIR = CACHE_DIR / "lyrics"
TRANSLATION_DIR = CACHE_DIR / "translations"
FONT_DIR = CACHE_DIR / "fonts"
TUNNEL_ORIGIN_HOST = "tunnel.local"
CACHE_MAX_AGE_DAYS = 30


def tunnel_route_allowed(method: str, path: str) -> bool:
    if method not in {"GET", "HEAD"}:
        return False
    if path in {"/overlay", "/api/state", "/api/config"}:
        return True
    return (
        path.startswith("/static/")
        or path.startswith("/artwork/")
        or path.startswith("/font-assets/")
    )


def tunnel_websocket_allowed(path: str) -> bool:
    """Apply the tunnel allowlist to WebSockets.

    ``BaseHTTPMiddleware`` only receives the ``http`` scope, so a handshake never
    reaches ``restrict_public_tunnel``.  The overlay feed is read-only and the
    public overlay already exposes the same data, so it stays allowed; anything
    else added later is refused by default.
    """
    return path == "/ws"


def build_user_agent() -> str:
    """MusicBrainz asks for an application name plus a way to reach the author.

    Define ``KOHS_CONTACT`` (an e-mail or a project URL) if MusicBrainz ever
    starts rejecting the anonymous form.
    """
    contact = os.environ.get("KOHS_CONTACT", "").strip()
    return f"KoHsSpotifyLyrics/1.0 ( {contact} )" if contact else (
        "KoHsSpotifyLyrics/1.0 (overlay local para Windows)"
    )


def prune_cache(directory: Path, max_age_days: int = CACHE_MAX_AGE_DAYS) -> int:
    """Drop cache entries untouched for a month so the folder cannot grow forever."""
    cutoff = time.time() - max_age_days * 86_400
    removed = 0
    try:
        entries = list(directory.iterdir())
    except OSError:
        return 0
    for entry in entries:
        if entry.name.startswith("."):
            continue
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink()
                removed += 1
        except OSError:
            logger.debug("No se pudo borrar %s", entry, exc_info=True)
    return removed


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("kohs-spotify-lyrics")


class WebSocketHub:
    def __init__(self):
        self._connections: list[WebSocket] = []
        self._broadcast_lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        async with self._broadcast_lock:
            connections = tuple(self._connections)

            async def send(websocket: WebSocket) -> tuple[WebSocket, bool]:
                try:
                    await asyncio.wait_for(websocket.send_json(message), timeout=1.0)
                    return websocket, True
                except Exception:
                    return websocket, False

            results = await asyncio.gather(*(send(websocket) for websocket in connections))
            for websocket, succeeded in results:
                if not succeeded:
                    self.disconnect(websocket)


def load_musixmatch_key() -> str | None:
    environment_key = os.environ.get("MUSIXMATCH_API_KEY", "").strip()
    if environment_key:
        return environment_key
    path = BASE_DIR / "secrets.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        value = str(payload.get("musixmatch_api_key") or "").strip()
        return value or None
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        logger.exception("No se pudo leer secrets.json")
        return None


hub = WebSocketHub()
config_manager = ConfigManager(BASE_DIR / "config.json")
font_catalog = LocalFontCatalog(FONT_DIR, BASE_DIR / "static" / "font-catalog.css")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(application: FastAPI):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ARTWORK_DIR.mkdir(parents=True, exist_ok=True)
    LYRICS_DIR.mkdir(parents=True, exist_ok=True)
    TRANSLATION_DIR.mkdir(parents=True, exist_ok=True)
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    expired = sum(prune_cache(folder) for folder in (ARTWORK_DIR, LYRICS_DIR, TRANSLATION_DIR))
    if expired:
        logger.info("Caché depurada: %d archivos con más de %d días", expired, CACHE_MAX_AGE_DAYS)
    musixmatch_key = load_musixmatch_key()
    headers = {"User-Agent": build_user_agent()}
    async with httpx.AsyncClient(headers=headers, timeout=10.0) as client:
        await font_catalog.prepare(client)
        application.state.http_client = client
        application.state.musixmatch_key = musixmatch_key
        coordinator = PlaybackCoordinator(
            spotify=SpotifySessionReader(),
            lyrics=LyricsProvider(LYRICS_DIR, client, musixmatch_key),
            artwork=ArtworkProvider(ARTWORK_DIR, client),
            broadcast=hub.broadcast,
            translation=TranslationProvider(TRANSLATION_DIR, client),
        )
        application.state.coordinator = coordinator
        task = asyncio.create_task(coordinator.run(), name="spotify-playback-monitor")
        logger.info("Monitor iniciado; fallback Musixmatch: %s", "activo" if musixmatch_key else "inactivo")
        try:
            yield
        finally:
            await coordinator.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


app = FastAPI(title="KoH's Spotify Lyrics", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["127.0.0.1", "localhost", "testserver", TUNNEL_ORIGIN_HOST],
)


@app.middleware("http")
async def restrict_public_tunnel(request: Request, call_next):
    if request.url.hostname == TUNNEL_ORIGIN_HOST:
        if not tunnel_route_allowed(request.method, request.url.path):
            return PlainTextResponse("Not found", status_code=404)
        response = await call_next(request)
        response.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable"
            if request.url.path.startswith("/font-assets/")
            and request.url.path != "/font-assets/catalog.css"
            else "no-store"
        )
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response
    response = await call_next(request)
    if request.url.path in {"/config", "/overlay"} or request.url.path.startswith(("/static/", "/font-assets/")):
        response.headers["Cache-Control"] = "no-store"
    return response
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/artwork", StaticFiles(directory=ARTWORK_DIR), name="artwork")


@app.get("/font-assets/catalog.css", include_in_schema=False)
async def local_font_catalog() -> Response:
    if not font_catalog.catalog_path.exists():
        return PlainTextResponse("Font catalog unavailable", status_code=503)
    return FileResponse(font_catalog.catalog_path, media_type="text/css")


@app.get("/font-assets/{filename}", include_in_schema=False)
async def local_font_asset(request: Request, filename: str) -> Response:
    client = getattr(request.app.state, "http_client", None)
    if not isinstance(client, httpx.AsyncClient):
        return PlainTextResponse("Font service unavailable", status_code=503)
    path = await font_catalog.asset_path(filename, client)
    if path is None:
        return PlainTextResponse("Not found", status_code=404)
    return FileResponse(path, media_type="font/woff2")


@app.get("/", include_in_schema=False)
async def root(request: Request) -> JSONResponse:
    base_url = str(request.base_url).rstrip("/")
    return JSONResponse(
        {
            "name": "KoH's Spotify Lyrics",
            "overlay": f"{base_url}/overlay",
            "config": f"{base_url}/config",
        }
    )


@app.get("/overlay", response_class=HTMLResponse, include_in_schema=False)
async def overlay(request: Request):
    return templates.TemplateResponse(request=request, name="overlay.html")


@app.head("/overlay", include_in_schema=False)
async def overlay_head() -> Response:
    return Response(status_code=200, media_type="text/html")


@app.get("/config", response_class=HTMLResponse, include_in_schema=False)
async def config_page(request: Request):
    return templates.TemplateResponse(request=request, name="config.html")


@app.get("/api/state")
async def get_state(request: Request) -> dict[str, Any]:
    coordinator = getattr(request.app.state, "coordinator", None)
    return coordinator.state if coordinator else empty_state()


@app.get("/api/config")
async def get_config() -> dict[str, Any]:
    return config_manager.get().model_dump(mode="json")


@app.put("/api/config")
async def update_config(config: OverlayConfig) -> dict[str, Any]:
    updated = config_manager.update(config)
    payload = updated.model_dump(mode="json")
    await hub.broadcast({"type": "config", "config": payload})
    return payload


@app.post("/api/config/reset")
async def reset_config() -> dict[str, Any]:
    updated = config_manager.reset()
    payload = updated.model_dump(mode="json")
    await hub.broadcast({"type": "config", "config": payload})
    return payload


@app.get("/api/health")
async def health(request: Request) -> dict[str, Any]:
    coordinator = getattr(request.app.state, "coordinator", None)
    state = coordinator.state if coordinator else empty_state()
    return {
        "ok": True,
        "winrt_available": WINRT_AVAILABLE,
        "status": state["status"],
        "visible": state["visible"],
        "musixmatch_fallback": bool(getattr(request.app.state, "musixmatch_key", None)),
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    if websocket.url.hostname == TUNNEL_ORIGIN_HOST and not tunnel_websocket_allowed(
        websocket.url.path
    ):
        await websocket.close(code=1008)
        return
    await hub.connect(websocket)
    coordinator = getattr(websocket.app.state, "coordinator", None)
    try:
        await websocket.send_json(coordinator.state if coordinator else empty_state())
        await websocket.send_json(
            {
                "type": "config",
                "config": config_manager.get().model_dump(mode="json"),
            }
        )
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.debug("WebSocket cerrado", exc_info=True)
    finally:
        hub.disconnect(websocket)


if __name__ == "__main__":
    certificate = BASE_DIR / "certs" / "localhost.pem"
    private_key = BASE_DIR / "certs" / "localhost-key.pem"
    http_only = os.environ.get("KOHS_HTTP_ONLY") == "1"
    if certificate.exists() and private_key.exists() and not http_only:
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=3443,
            log_level="info",
            ssl_certfile=str(certificate),
            ssl_keyfile=str(private_key),
        )
    else:
        uvicorn.run(app, host="127.0.0.1", port=3000, log_level="info")
