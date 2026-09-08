from __future__ import annotations

import asyncio

import pytest

from lyrics import LyricsResult
from spotify_session import SpotifySnapshot, SpotifyTrack
from state_manager import PlaybackCoordinator
from translation import TranslationResult


class FakeSpotify:
    async def poll(self, _metadata_due):
        return None


class FakeArtwork:
    async def save_windows_fallback(self, _query, _content):
        return "/artwork/fallback.jpg"

    async def resolve_high_resolution(self, _query):
        return "/artwork/highres.jpg"


class FakeLyrics:
    def __init__(self, lines, gate: asyncio.Event | None = None, timing="synced"):
        self.lines = lines
        self.gate = gate
        self.timing = timing

    async def get_synced(self, _query):
        if self.gate:
            await self.gate.wait()
        return LyricsResult(self.lines, timing=self.timing)


class SlowArtwork(FakeArtwork):
    def __init__(self, gate: asyncio.Event):
        self.gate = gate

    async def resolve_high_resolution(self, _query):
        await self.gate.wait()
        return "/artwork/highres.jpg"


class LateWindowsArtwork(FakeArtwork):
    async def save_windows_fallback(self, _query, content):
        return "/artwork/late.png" if content else None

    async def resolve_high_resolution(self, _query):
        return None


class FakeTranslation:
    async def translate_lines(self, _query, lines):
        return TranslationResult(
            [f"ES: {line['text']}" for line in lines],
            provider="Prueba",
        )


def snapshot(key="one", title="Tema", position=1_000, active=True):
    return SpotifySnapshot(
        track=SpotifyTrack(key, title, "Artista", "Álbum", 180_000),
        position_ms=position,
        playback_status="playing" if active else "stopped",
        is_playing=active,
        is_active=active,
        observed_at_ms=1000,
    )


def snapshot_with_artwork(content: bytes | None):
    value = snapshot()
    value.artwork_bytes = content
    return value


@pytest.mark.asyncio
async def test_overlay_metadata_is_visible_while_lyrics_are_resolved():
    messages = []

    async def broadcast(message):
        messages.append(message.copy())

    coordinator = PlaybackCoordinator(
        FakeSpotify(),
        FakeLyrics([{"time_ms": 1000, "text": "Línea"}]),
        FakeArtwork(),
        broadcast,
    )
    await coordinator._consume(snapshot())
    assert coordinator.state["visible"] is True
    assert coordinator.state["status"] == "loading_lyrics"
    await coordinator._resolver
    assert coordinator.state["visible"] is True
    assert coordinator.state["lyrics"][0]["text"] == "Línea"


@pytest.mark.asyncio
async def test_plain_or_missing_lyrics_keep_metadata_visible():
    async def broadcast(_message):
        return None

    coordinator = PlaybackCoordinator(
        FakeSpotify(), FakeLyrics([]), FakeArtwork(), broadcast
    )
    await coordinator._consume(snapshot())
    await coordinator._resolver
    assert coordinator.state["visible"] is True
    assert coordinator.state["status"] == "no_synced_lyrics"
    assert coordinator.state["track"]["title"] == "Tema"


@pytest.mark.asyncio
async def test_estimated_lyrics_are_rejected_and_metadata_stays_visible():
    async def broadcast(_message):
        return None

    coordinator = PlaybackCoordinator(
        FakeSpotify(),
        FakeLyrics([{"time_ms": 1000, "text": "Línea"}], timing="estimated"),
        FakeArtwork(),
        broadcast,
    )
    await coordinator._consume(snapshot())
    await coordinator._resolver
    assert coordinator.state["visible"] is True
    assert coordinator.state["status"] == "no_synced_lyrics"
    assert coordinator.state["lyrics"] == []
    assert coordinator.state["lyrics_timing"] is None


@pytest.mark.asyncio
async def test_track_change_updates_metadata_immediately_and_old_result_cannot_leak():
    async def broadcast(_message):
        return None

    gate = asyncio.Event()
    coordinator = PlaybackCoordinator(
        FakeSpotify(),
        FakeLyrics([{"time_ms": 0, "text": "Vieja"}], gate),
        FakeArtwork(),
        broadcast,
    )
    await coordinator._consume(snapshot("old", "Anterior"))
    await coordinator._consume(snapshot("new", "Nueva"))
    assert coordinator.state["visible"] is True
    assert coordinator.state["track"]["title"] == "Nueva"
    gate.set()
    await coordinator._resolver
    assert coordinator.state["lyrics"][0]["text"] == "Vieja"
    assert coordinator.state["track"]["key"] == "new"


@pytest.mark.asyncio
async def test_spotify_disappearing_clears_visible_state():
    async def broadcast(_message):
        return None

    coordinator = PlaybackCoordinator(
        FakeSpotify(),
        FakeLyrics([{"time_ms": 0, "text": "Línea"}]),
        FakeArtwork(),
        broadcast,
    )
    await coordinator._consume(snapshot())
    await coordinator._resolver
    assert coordinator.state["visible"] is True
    await coordinator._consume(None)
    assert coordinator.state["visible"] is False
    assert coordinator.state["track"] is None


@pytest.mark.asyncio
async def test_translation_is_published_without_waiting_for_highres_artwork():
    artwork_gate = asyncio.Event()
    translated = asyncio.Event()

    async def broadcast(message):
        if message.get("translation_provider") == "Prueba":
            translated.set()

    coordinator = PlaybackCoordinator(
        FakeSpotify(),
        FakeLyrics([{"time_ms": 0, "text": "Hello"}]),
        SlowArtwork(artwork_gate),
        broadcast,
        translation=FakeTranslation(),
    )
    await coordinator._consume(snapshot())
    await asyncio.wait_for(translated.wait(), timeout=1)

    assert coordinator.state["lyrics"][0]["translation"] == "ES: Hello"
    assert coordinator.state["track"]["artwork_url"] == "/artwork/fallback.jpg"

    artwork_gate.set()
    await coordinator._resolver
    assert coordinator.state["track"]["artwork_url"] == "/artwork/highres.jpg"


@pytest.mark.asyncio
async def test_late_windows_artwork_is_published_for_the_current_track():
    async def broadcast(_message):
        return None

    coordinator = PlaybackCoordinator(
        FakeSpotify(), FakeLyrics([]), LateWindowsArtwork(), broadcast
    )
    await coordinator._consume(snapshot_with_artwork(None))
    await coordinator._resolver
    assert coordinator.state["track"]["artwork_url"] is None

    await coordinator._consume(snapshot_with_artwork(b"late-cover"))
    assert coordinator.state["track"]["artwork_url"] == "/artwork/late.png"


@pytest.mark.asyncio
async def test_identical_playback_frames_are_not_rebroadcast():
    messages = []

    async def broadcast(message):
        messages.append(message.copy())

    coordinator = PlaybackCoordinator(
        FakeSpotify(),
        FakeLyrics([{"time_ms": 0, "text": "Línea"}]),
        FakeArtwork(),
        broadcast,
    )
    paused = snapshot(active=False)
    await coordinator._consume(paused)
    await coordinator._resolver
    sent = len(messages)

    for _ in range(4):
        paused.observed_at_ms += 250
        await coordinator._consume(paused)
    assert len(messages) == sent + 1, "una pausa no debe emitir cuatro mensajes por segundo"

    paused.position_ms += 1_000
    await coordinator._consume(paused)
    assert len(messages) == sent + 2, "un seek sí debe publicarse"
