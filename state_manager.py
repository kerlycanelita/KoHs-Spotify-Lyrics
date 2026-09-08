from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from artwork import ArtworkProvider
from lyrics import LyricsProvider, TrackQuery
from spotify_session import SpotifySessionReader, SpotifySnapshot
from translation import TranslationProvider


logger = logging.getLogger(__name__)
Broadcast = Callable[[dict[str, Any]], Awaitable[None]]


def empty_state(status: str = "starting") -> dict[str, Any]:
    return {
        "type": "state",
        "revision": 0,
        "visible": False,
        "status": status,
        "track": None,
        "playback": None,
        "lyrics": [],
        "lyrics_provider": None,
        "lyrics_timing": None,
        "translation_provider": None,
    }


class PlaybackCoordinator:
    POLL_INTERVAL = 0.25
    METADATA_INTERVAL = 1.0

    def __init__(
        self,
        spotify: SpotifySessionReader,
        lyrics: LyricsProvider,
        artwork: ArtworkProvider,
        broadcast: Broadcast,
        translation: TranslationProvider | None = None,
    ):
        self.spotify = spotify
        self.lyrics = lyrics
        self.artwork = artwork
        self.broadcast = broadcast
        self.translation = translation
        self.state = empty_state()
        self._current_key: str | None = None
        self._lyrics_lines: list[dict[str, Any]] = []
        self._lyrics_timing: str | None = None
        self._resolver: asyncio.Task[None] | None = None
        self._running = False
        self._last_metadata_poll = 0.0
        self._last_playback_signature: tuple[Any, ...] | None = None

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        self._running = True
        while self._running:
            started = loop.time()
            metadata_due = started - self._last_metadata_poll >= self.METADATA_INTERVAL
            if metadata_due:
                self._last_metadata_poll = started
            snapshot = await self.spotify.poll(metadata_due)
            try:
                await self._consume(snapshot)
            except Exception:
                logger.exception("Error actualizando el estado del overlay")
                await self._hide("internal_error", clear_track=False)
            elapsed = loop.time() - started
            await asyncio.sleep(max(0.02, self.POLL_INTERVAL - elapsed))

    async def stop(self) -> None:
        self._running = False
        if self._resolver and not self._resolver.done():
            self._resolver.cancel()
            await asyncio.gather(self._resolver, return_exceptions=True)

    async def _consume(self, snapshot: SpotifySnapshot | None) -> None:
        if snapshot is None:
            if self._current_key is not None:
                self._cancel_resolver()
                self._current_key = None
                self._lyrics_lines = []
                self._lyrics_timing = None
                await self._replace_state(empty_state("spotify_unavailable"))
            elif self.state["status"] != "spotify_unavailable":
                await self._replace_state(empty_state("spotify_unavailable"))
            return

        if snapshot.track.key != self._current_key:
            await self._begin_track(snapshot)
            return

        current_artwork = (
            self.state.get("track", {}).get("artwork_url")
            if isinstance(self.state.get("track"), dict)
            else None
        )
        if not current_artwork and snapshot.artwork_bytes:
            query = TrackQuery(
                key=snapshot.track.key,
                title=snapshot.track.title,
                artist=snapshot.track.artist,
                album=snapshot.track.album,
                duration_ms=snapshot.track.duration_ms,
            )
            current_artwork = await self.artwork.save_windows_fallback(
                query, snapshot.artwork_bytes
            )
        self.state["track"] = self._track_payload(snapshot, current_artwork)
        self.state["playback"] = self._playback_payload(snapshot)
        self.state["visible"] = bool(snapshot.is_active)
        if self._lyrics_lines:
            self.state["status"] = "ready" if snapshot.is_active else "not_playing"
        elif self.state["status"] not in {"loading_lyrics", "no_synced_lyrics"}:
            self.state["status"] = "no_synced_lyrics"
        await self._publish_playback()

    async def _begin_track(self, snapshot: SpotifySnapshot) -> None:
        self._cancel_resolver()
        self._current_key = snapshot.track.key
        self._lyrics_lines = []
        self._lyrics_timing = None
        logger.info("Cambio de canción detectado: %s — %s", snapshot.track.artist, snapshot.track.title)
        query = TrackQuery(
            key=snapshot.track.key,
            title=snapshot.track.title,
            artist=snapshot.track.artist,
            album=snapshot.track.album,
            duration_ms=snapshot.track.duration_ms,
        )
        fallback_url = await self.artwork.save_windows_fallback(
            query, snapshot.artwork_bytes
        )
        self.state = {
            "type": "state",
            "revision": self.state["revision"],
            "visible": bool(snapshot.is_active),
            "status": "loading_lyrics" if snapshot.is_active else "not_playing",
            "track": self._track_payload(snapshot, fallback_url),
            "playback": self._playback_payload(snapshot),
            "lyrics": [],
            "lyrics_provider": None,
            "lyrics_timing": None,
            "translation_provider": None,
        }
        await self._publish()
        self._resolver = asyncio.create_task(
            self._resolve_track(query), name=f"resolve-{query.key}"
        )

    async def _resolve_track(self, query: TrackQuery) -> None:
        artwork_task = asyncio.create_task(self.artwork.resolve_high_resolution(query))
        translation_task: asyncio.Task | None = None
        try:
            result = await self.lyrics.get_synced(query)
            if query.key != self._current_key:
                return
            accepted_lines = result.lines if result.timing == "synced" else []
            if result.lines and not accepted_lines:
                logger.warning("Letra sin timestamps reales rechazada para %s", query.key)
            self._lyrics_lines = [dict(line) for line in accepted_lines]
            self._lyrics_timing = "synced" if accepted_lines else None
            self.state["lyrics"] = self._lyrics_lines
            self.state["lyrics_provider"] = result.provider if accepted_lines else None
            self.state["lyrics_timing"] = self._lyrics_timing
            self.state["translation_provider"] = None
            playback = self.state.get("playback")
            active = bool(playback.get("is_active")) if isinstance(playback, dict) else False
            self.state["visible"] = active
            self.state["status"] = (
                "ready" if accepted_lines and active
                else "not_playing" if accepted_lines
                else "no_synced_lyrics"
            )
            await self._publish()

            if accepted_lines and self.translation is not None:
                translation_task = asyncio.create_task(
                    self.translation.translate_lines(query, self._lyrics_lines),
                    name=f"translate-{query.key}",
                )

            publishers = [self._publish_artwork_when_ready(query, artwork_task)]
            if translation_task is not None:
                publishers.append(
                    self._publish_translation_when_ready(query, translation_task)
                )
            await asyncio.gather(*publishers)
        except asyncio.CancelledError:
            artwork_task.cancel()
            if translation_task is not None:
                translation_task.cancel()
            await asyncio.gather(
                *(task for task in (artwork_task, translation_task) if task is not None),
                return_exceptions=True,
            )
            raise
        except Exception:
            logger.exception("No se pudo resolver la canción %s", query.key)
            if query.key == self._current_key:
                self._lyrics_lines = []
                self.state["visible"] = self._current_playback_active()
                await self._hide("no_synced_lyrics", clear_track=False, preserve_visibility=True)
        finally:
            if not artwork_task.done():
                artwork_task.cancel()

    async def _publish_artwork_when_ready(
        self, query: TrackQuery, artwork_task: asyncio.Task
    ) -> None:
        try:
            highres_url = await artwork_task
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("No se pudo mejorar la portada de %s", query.title)
            return
        if highres_url and query.key == self._current_key and self.state.get("track"):
            self.state["track"]["artwork_url"] = highres_url
            await self._publish()

    async def _publish_translation_when_ready(
        self, query: TrackQuery, translation_task: asyncio.Task
    ) -> None:
        try:
            translated = await translation_task
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("No se pudo traducir %s", query.title, exc_info=True)
            return
        if query.key != self._current_key:
            return
        for line, translation in zip(
            self._lyrics_lines, translated.texts, strict=False
        ):
            line["translation"] = translation
        self.state["lyrics"] = self._lyrics_lines
        self.state["translation_provider"] = translated.provider
        await self._publish()

    async def _hide(
        self, status: str, clear_track: bool, preserve_visibility: bool = False
    ) -> None:
        if not preserve_visibility:
            self.state["visible"] = False
        self.state["status"] = status
        self.state["lyrics"] = []
        self.state["lyrics_provider"] = None
        self.state["lyrics_timing"] = None
        self.state["translation_provider"] = None
        if clear_track:
            self.state["track"] = None
            self.state["playback"] = None
        await self._publish()

    def _current_playback_active(self) -> bool:
        playback = self.state.get("playback")
        return bool(playback.get("is_active")) if isinstance(playback, dict) else False

    async def _replace_state(self, new_state: dict[str, Any]) -> None:
        new_state["revision"] = self.state["revision"]
        self.state = new_state
        await self._publish()

    async def _publish(self) -> None:
        self.state["revision"] += 1
        self._last_playback_signature = None
        await self.broadcast(self.state.copy())

    async def _publish_playback(self) -> None:
        """Send the frequently changing clock without resending all lyrics.

        ``observed_at_ms`` advances on every poll, so it stays out of the
        signature: while Spotify is paused nothing else moves and the frame is
        dropped instead of pushing four identical messages per second.
        """
        playback = self.state["playback"] if isinstance(self.state["playback"], dict) else {}
        signature = (
            self.state["visible"],
            self.state["status"],
            playback.get("position_ms"),
            playback.get("duration_ms"),
            playback.get("status"),
            playback.get("is_playing"),
            playback.get("is_active"),
        )
        if signature == self._last_playback_signature:
            return
        self._last_playback_signature = signature
        self.state["revision"] += 1
        await self.broadcast(
            {
                "type": "playback",
                "revision": self.state["revision"],
                "visible": self.state["visible"],
                "status": self.state["status"],
                "playback": self.state["playback"],
            }
        )

    def _cancel_resolver(self) -> None:
        if self._resolver and not self._resolver.done():
            self._resolver.cancel()
        self._resolver = None

    @staticmethod
    def _track_payload(
        snapshot: SpotifySnapshot, artwork_url: str | None = None
    ) -> dict[str, Any]:
        return {
            "key": snapshot.track.key,
            "title": snapshot.track.title,
            "artist": snapshot.track.artist,
            "album": snapshot.track.album,
            "duration_ms": snapshot.track.duration_ms,
            "artwork_url": artwork_url,
        }

    @staticmethod
    def _playback_payload(snapshot: SpotifySnapshot) -> dict[str, Any]:
        return {
            "position_ms": snapshot.position_ms,
            "duration_ms": snapshot.track.duration_ms,
            "status": snapshot.playback_status,
            "is_playing": snapshot.is_playing,
            "is_active": snapshot.is_active,
            "observed_at_ms": snapshot.observed_at_ms,
        }
