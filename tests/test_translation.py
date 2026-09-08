from __future__ import annotations

import httpx
import pytest

from lyrics import TrackQuery
from translation import TranslationProvider


@pytest.mark.asyncio
async def test_translation_preserves_line_mapping_and_uses_cache(tmp_path):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.params["langpair"] == "autodetect|es"
        return httpx.Response(
            200,
            json={
                "responseStatus": 200,
                "responseData": {"translatedText": "Hola mundo\nSigue cantando"},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = TranslationProvider(tmp_path, client)
        query = TrackQuery("track", "Song", "Artist", "Album", 100_000)
        lines = [
            {"time_ms": 0, "text": "Hello world"},
            {"time_ms": 1000, "text": "Keep singing"},
        ]
        result = await provider.translate_lines(query, lines)
        cached = await provider.translate_lines(query, lines)

    assert result.texts == ["Hola mundo", "Sigue cantando"]
    assert result.provider == "MyMemory"
    assert cached.cached is True
    assert calls == 1


@pytest.mark.asyncio
async def test_spanish_source_is_kept_when_provider_detects_same_language(tmp_path):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "responseStatus": 200,
                "responseDetails": "PLEASE SELECT TWO DISTINCT LANGUAGES",
                "responseData": {"translatedText": "PLEASE SELECT TWO DISTINCT LANGUAGES"},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = TranslationProvider(tmp_path, client)
        result = await provider.translate_lines(
            TrackQuery("es", "Canción", "Artista", "Álbum", 90_000),
            [{"time_ms": 0, "text": "Ya está en español"}],
        )

    assert result.texts == ["Ya está en español"]


@pytest.mark.asyncio
async def test_google_fallback_is_used_when_mymemory_quota_is_exhausted(tmp_path):
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        if request.url.host == "api.mymemory.translated.net":
            return httpx.Response(
                200,
                json={
                    "responseStatus": 429,
                    "responseDetails": "FREE TRANSLATIONS FOR TODAY EXHAUSTED",
                    "responseData": {"translatedText": "quota reached"},
                },
            )
        assert request.url.host == "translate.googleapis.com"
        return httpx.Response(
            200,
            json=[
                [
                    ["Hola mundo\n", "Hello world\n"],
                    ["Sigue cantando", "Keep singing"],
                ],
                None,
                "en",
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = TranslationProvider(tmp_path, client)
        result = await provider.translate_lines(
            TrackQuery("fallback", "Song", "Artist", "Album", 100_000),
            [
                {"time_ms": 0, "text": "Hello world"},
                {"time_ms": 1000, "text": "Keep singing"},
            ],
        )

    assert result.texts == ["Hola mundo", "Sigue cantando"]
    assert result.provider == "Google (respaldo)"
    assert hosts == ["api.mymemory.translated.net", "translate.googleapis.com"]


@pytest.mark.asyncio
async def test_old_empty_cache_is_retried_with_new_provider_pipeline(tmp_path):
    query = TrackQuery("old-cache", "Song", "Artist", "Album", 100_000)
    (tmp_path / "old-cache-es.json").write_text(
        '{"source_texts":["Hello"],"translations":[""],"retry_after":9999999999}',
        encoding="utf-8",
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "responseStatus": 200,
                "responseData": {"translatedText": "Hola"},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await TranslationProvider(tmp_path, client).translate_lines(
            query,
            [{"time_ms": 0, "text": "Hello"}],
        )

    assert result.texts == ["Hola"]


@pytest.mark.asyncio
async def test_active_google_fallback_translates_a_song_in_one_large_batch(tmp_path):
    calls = 0
    lines = [f"Line {index}" for index in range(40)]

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.host == "translate.googleapis.com"
        translated = request.url.params["q"].replace("Line", "Línea")
        return httpx.Response(200, json=[[[translated, request.url.params["q"]]]])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = TranslationProvider(tmp_path, client)
        provider._mymemory_unavailable_until = float("inf")
        result = await provider.translate_lines(
            TrackQuery("fast", "Song", "Artist", "Album", 100_000),
            [
                {"time_ms": index * 1000, "text": text}
                for index, text in enumerate(lines)
            ],
        )

    assert result.texts == [f"Línea {index}" for index in range(40)]
    assert result.provider == "Google (respaldo)"
    assert calls == 1
