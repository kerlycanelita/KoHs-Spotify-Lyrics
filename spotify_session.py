from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from lyrics import track_cache_key


logger = logging.getLogger(__name__)

try:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager,
    )
    from winrt.windows.storage.streams import Buffer, InputStreamOptions

    WINRT_AVAILABLE = True
except (ImportError, OSError):
    GlobalSystemMediaTransportControlsSessionManager = None  # type: ignore[assignment]
    Buffer = None  # type: ignore[assignment]
    InputStreamOptions = None  # type: ignore[assignment]
    WINRT_AVAILABLE = False


@dataclass(slots=True)
class SpotifyTrack:
    key: str
    title: str
    artist: str
    album: str
    duration_ms: int


@dataclass(slots=True)
class SpotifySnapshot:
    track: SpotifyTrack
    position_ms: int
    playback_status: str
    is_playing: bool
    is_active: bool
    observed_at_ms: int
    artwork_bytes: bytes | None = None


class SpotifySessionReader:
    def __init__(self):
        self._manager: Any | None = None
        self._session: Any | None = None
        self._track: SpotifyTrack | None = None
        self._artwork_loaded_key: str | None = None
        self._last_error_log = 0.0

    async def poll(self, metadata_due: bool) -> SpotifySnapshot | None:
        if not WINRT_AVAILABLE:
            self._log_throttled(
                "WinRT no está instalado. Ejecuta iniciar.bat para instalar las dependencias."
            )
            return None

        try:
            if self._manager is None:
                self._manager = (
                    await GlobalSystemMediaTransportControlsSessionManager.request_async()
                )
            if metadata_due or self._session is None:
                self._session = self._select_spotify_session()
            if self._session is None:
                self._track = None
                self._artwork_loaded_key = None
                return None

            playback = self._session.get_playback_info()
            timeline = self._session.get_timeline_properties()
            status = self._status_name(playback.playback_status)
            position_ms, duration_ms = self._timeline_values(timeline, status)

            artwork_bytes = None
            if metadata_due or self._track is None:
                properties = await self._session.try_get_media_properties_async()
                title = str(getattr(properties, "title", "") or "").strip()
                artist = str(getattr(properties, "artist", "") or "").strip()
                album = str(getattr(properties, "album_title", "") or "").strip()
                if not title or not artist:
                    self._track = None
                    return None
                key = track_cache_key(title, artist, album, duration_ms)
                track_changed = self._track is None or key != self._track.key
                self._track = SpotifyTrack(
                    key=key,
                    title=title,
                    artist=artist,
                    album=album,
                    duration_ms=duration_ms,
                )
                if track_changed or self._artwork_loaded_key != key:
                    artwork_bytes = await self._read_thumbnail(
                        getattr(properties, "thumbnail", None)
                    )
                    if artwork_bytes:
                        self._artwork_loaded_key = key
            elif self._track.duration_ms != duration_ms and duration_ms > 0:
                key = track_cache_key(
                    self._track.title,
                    self._track.artist,
                    self._track.album,
                    duration_ms,
                )
                self._track = SpotifyTrack(
                    key=key,
                    title=self._track.title,
                    artist=self._track.artist,
                    album=self._track.album,
                    duration_ms=duration_ms,
                )

            if self._track is None:
                return None
            return SpotifySnapshot(
                track=self._track,
                position_ms=position_ms,
                playback_status=status,
                is_playing=status == "playing",
                is_active=status in {"playing", "paused"},
                observed_at_ms=round(time.time() * 1000),
                artwork_bytes=artwork_bytes,
            )
        except Exception:
            self._log_throttled("No se pudo leer la sesión multimedia de Spotify", exception=True)
            self._manager = None
            self._session = None
            self._track = None
            self._artwork_loaded_key = None
            return None

    def _select_spotify_session(self) -> Any | None:
        sessions = list(self._manager.get_sessions())
        spotify_sessions = [
            session
            for session in sessions
            if "spotify" in str(getattr(session, "source_app_user_model_id", "")).lower()
        ]
        if not spotify_sessions:
            return None
        current = self._manager.get_current_session()
        if current in spotify_sessions:
            return current
        return max(
            spotify_sessions,
            key=lambda session: self._status_name(
                session.get_playback_info().playback_status
            )
            == "playing",
        )

    @staticmethod
    def _status_name(status: Any) -> str:
        name = getattr(status, "name", None)
        if name:
            return str(name).lower()
        numeric_names = {
            0: "closed",
            1: "opened",
            2: "changing",
            3: "stopped",
            4: "playing",
            5: "paused",
        }
        try:
            return numeric_names.get(int(status), "unknown")
        except (TypeError, ValueError):
            return "unknown"

    @staticmethod
    def _timeline_values(timeline: Any, status: str) -> tuple[int, int]:
        start_ms = max(0, round(timeline.start_time.total_seconds() * 1000))
        end_ms = max(0, round(timeline.end_time.total_seconds() * 1000))
        position_ms = max(0, round(timeline.position.total_seconds() * 1000))
        duration_ms = max(0, end_ms - start_ms)
        if duration_ms == 0:
            duration_ms = end_ms

        if status == "playing":
            last_updated = getattr(timeline, "last_updated_time", None)
            if isinstance(last_updated, datetime):
                if last_updated.tzinfo is None:
                    last_updated = last_updated.replace(tzinfo=timezone.utc)
                elapsed_ms = round(
                    (datetime.now(timezone.utc) - last_updated.astimezone(timezone.utc)).total_seconds()
                    * 1000
                )
                position_ms += max(0, elapsed_ms)

        if duration_ms > 0:
            position_ms = min(position_ms, duration_ms)
        return position_ms, duration_ms

    @staticmethod
    async def _read_thumbnail(reference: Any | None) -> bytes | None:
        if reference is None or Buffer is None or InputStreamOptions is None:
            return None
        try:
            stream = await reference.open_read_async()
            size = min(int(stream.size), 15 * 1024 * 1024)
            if size <= 0:
                return None
            buffer = Buffer(size)
            result = await stream.read_async(buffer, size, InputStreamOptions.READ_AHEAD)
            try:
                return bytes(memoryview(result))
            except TypeError:
                return bytes(result)
        except Exception:
            logger.exception("No se pudo leer la portada entregada por Windows")
            return None

    def _log_throttled(self, message: str, exception: bool = False) -> None:
        now = time.monotonic()
        if now - self._last_error_log < 30:
            return
        self._last_error_log = now
        if exception:
            logger.exception(message)
        else:
            logger.warning(message)
