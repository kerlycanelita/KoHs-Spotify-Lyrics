from __future__ import annotations

import httpx
import pytest

from lyrics import (
    LyricsProvider,
    TrackQuery,
    has_valid_synced_timeline,
    lrclib_record_matches,
    parse_lrc,
    parse_ttml,
    strip_embedded_translations,
    track_cache_key,
)


def test_parse_lrc_accepts_real_timestamps_and_multiple_tags():
    lines = parse_lrc(
        "[ar:Artist]\n[00:12.40][00:14.400] Primera línea\n[01:02] Segunda línea",
        duration_ms=70_000,
    )
    assert lines == [
        {"time_ms": 12_400, "text": "Primera línea"},
        {"time_ms": 14_400, "text": "Primera línea"},
        {"time_ms": 62_000, "text": "Segunda línea"},
    ]


def test_parse_lrc_rejects_plain_text_and_invalid_times():
    value = "Texto plano\nSin timestamps\n[00:65.00] inválida\n[04:00.00] fuera"
    assert parse_lrc(value, duration_ms=120_000) == []


def test_parse_ttml_uses_line_time_and_ignores_translation_nodes():
    value = """<tt xmlns="http://www.w3.org/ns/ttml" xmlns:ttm="http://www.w3.org/ns/ttml#metadata">
    <body><div><p begin="1:02.500"><span>Hello</span> <span>world</span>
    <span ttm:role="x-translation">Hola mundo</span></p></div></body></tt>"""
    assert parse_ttml(value, 70_000) == [
        {"time_ms": 62_500, "text": "Hello world"}
    ]


def test_synced_timeline_requires_multiple_real_timestamps():
    assert not has_valid_synced_timeline([{"time_ms": 1_000, "text": "Una"}], 10_000)
    assert not has_valid_synced_timeline(
        [{"time_ms": 1_000, "text": "Una"}, {"time_ms": 1_000, "text": "Dos"}],
        10_000,
    )
    assert has_valid_synced_timeline(
        [{"time_ms": 1_000, "text": "Una"}, {"time_ms": 3_000, "text": "Dos"}],
        10_000,
    )


def test_lrclib_match_requires_exact_track_artist_album_and_close_duration():
    query = TrackQuery("key", "Tema", "Artista", "Álbum", 180_000)
    exact = {
        "trackName": "Tema",
        "artistName": "Artista",
        "albumName": "Álbum",
        "duration": 181.5,
    }
    assert lrclib_record_matches(query, exact)
    assert not lrclib_record_matches(query, {**exact, "albumName": "Otro álbum"})
    assert not lrclib_record_matches(query, {**exact, "duration": 184.0})
    assert not lrclib_record_matches(query, {**exact, "trackName": "Otro tema"})


def test_track_key_is_normalized_but_includes_duration():
    first = track_cache_key("Canción", "Ártista", "Álbum", 180_200)
    equivalent = track_cache_key("cancion", "artista", "album", 180_400)
    different_duration = track_cache_key("cancion", "artista", "album", 184_000)
    assert first == equivalent
    assert first != different_duration


def test_track_key_preserves_japanese_titles():
    first = track_cache_key("邪神の婚礼、儀は愛と知る。", "Imperial Circus Dead Decadence", "狂おしく咲いた", 301_813)
    second = track_cache_key("残酷さは其の亡骸を舐らざる", "Imperial Circus Dead Decadence", "狂おしく咲いた", 302_000)
    assert first != second


@pytest.mark.asyncio
async def test_cache_from_a_different_track_is_rejected(tmp_path):
    path = tmp_path / "collision.json"
    path.write_text(
        '{"cache_version":4,"track":{"title":"別の曲","artist":"Artist","album":"Album","duration_ms":180000},"lines":[]}',
        encoding="utf-8",
    )

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(404))) as client:
        provider = LyricsProvider(tmp_path, client)
        query = TrackQuery("collision", "現在の曲", "Artist", "Album", 180_000)
        assert provider._read_cache(query) is None


@pytest.mark.asyncio
async def test_musixmatch_is_used_only_after_lrclib_has_no_synced_result(tmp_path, monkeypatch):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("lyrics.asyncio.sleep", no_sleep)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.host == "lrclib.net" and request.url.path == "/api/get":
            return httpx.Response(404, json={"code": 404})
        if request.url.host == "lrclib.net":
            return httpx.Response(200, json=[])
        return httpx.Response(
            200,
            json={
                "message": {
                    "header": {"status_code": 200},
                    "body": {"subtitle": {"subtitle_body": "[00:01.00] Uno\n[00:03.50] Dos"}},
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = LyricsProvider(tmp_path, client, "secret-key")
        query = TrackQuery("track-key", "Tema", "Artista", "Álbum", 10_000)
        result = await provider.get_synced(query)
        cached = await provider.get_synced(query)

    assert result.provider == "Musixmatch"
    assert result.lines[-1] == {"time_ms": 3500, "text": "Dos"}
    assert cached.cached is True
    assert cached.provider == "Musixmatch"
    # Musixmatch va el último: sólo se consulta cuando ninguna fuente libre
    # devolvió timestamps. La segunda llamada no repite ninguna petición.
    assert [httpx.URL(url).host for url in calls] == [
        "lrclib.net",
        "lrclib.net",
        "api.amll.dev",
        "music.163.com",
        "api.musixmatch.com",
    ]


@pytest.mark.asyncio
async def test_plain_lyrics_without_real_timestamps_are_not_shown(tmp_path, monkeypatch):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("lyrics.asyncio.sleep", no_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/get":
            return httpx.Response(
                200,
                json={
                    "trackName": "Tema",
                    "artistName": "Artista",
                    "albumName": "Álbum",
                    "duration": 10,
                    "plainLyrics": "Primera línea\n\nSegunda línea",
                    "syncedLyrics": None,
                },
            )
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = LyricsProvider(tmp_path, client)
        result = await provider.get_synced(
            TrackQuery("plain-key", "Tema", "Artista", "Álbum", 10_000)
        )

    assert result.timing == "synced"
    assert result.lines == []


@pytest.mark.asyncio
async def test_lrclib_rejects_synced_lyrics_from_wrong_album(tmp_path, monkeypatch):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("lyrics.asyncio.sleep", no_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "lrclib.net" and request.url.path == "/api/get":
            return httpx.Response(200, json={
                "trackName": "Tema",
                "artistName": "Artista",
                "albumName": "Álbum equivocado",
                "duration": 10,
                "syncedLyrics": "[00:01.00] Una\n[00:03.00] Dos",
            })
        if request.url.host == "lrclib.net":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"data": {"items": []}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await LyricsProvider(tmp_path, client).get_synced(
            TrackQuery("wrong-album", "Tema", "Artista", "Álbum", 10_000)
        )

    assert result.lines == []


@pytest.mark.asyncio
async def test_amll_is_used_when_lrclib_has_no_synced_lyrics(tmp_path, monkeypatch):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("lyrics.asyncio.sleep", no_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "lrclib.net" and request.url.path == "/api/get":
            return httpx.Response(404, json={"code": 404})
        if request.url.host == "lrclib.net":
            return httpx.Response(200, json=[])
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"data": {"items": [{
                "id": 7,
                "musicNames": ["Tema"],
                "artistNames": ["Artista"],
                "albumNames": ["Álbum"],
            }]}})
        return httpx.Response(200, json={"data": {"lyrics": (
            '<tt xmlns="http://www.w3.org/ns/ttml"><body><div>'
            '<p begin="3.2"><span>Uno</span></p>'
            '<p begin="5.4"><span>Dos</span></p>'
            '</div></body></tt>'
        )}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await LyricsProvider(tmp_path, client).get_synced(
            TrackQuery("amll-key", "Tema", "Artista", "Álbum", 10_000)
        )

    assert result.provider == "AMLL"
    assert result.timing == "synced"
    assert result.lines == [
        {"time_ms": 3_200, "text": "Uno"},
        {"time_ms": 5_400, "text": "Dos"},
    ]

@pytest.mark.asyncio
async def test_netease_supplies_timestamps_when_lrclib_only_has_plain_text(tmp_path, monkeypatch):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("lyrics.asyncio.sleep", no_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "lrclib.net" and request.url.path == "/api/get":
            return httpx.Response(200, json={
                "trackName": "Tema",
                "artistName": "Artista",
                "albumName": "Álbum",
                "duration": 240.0,
                "plainLyrics": "Uno\nDos",
                "syncedLyrics": None,
            })
        if request.url.host == "lrclib.net":
            return httpx.Response(200, json=[])
        if request.url.host == "api.amll.dev":
            return httpx.Response(200, json={"data": {"items": []}})
        if request.url.path == "/api/cloudsearch/pc":
            return httpx.Response(200, json={"result": {"songs": [{
                "id": 42,
                "name": "Tema",
                "dt": 240_000,
                "ar": [{"name": "Artista"}],
            }]}})
        return httpx.Response(200, json={"lrc": {"lyric": (
            "[00:00.000]作词 : Alguien\n"
            "[00:01.000]Composed by : Otro\n"
            "[00:12.400]Primera línea\n"
            "[00:16.800]Segunda línea\n"
        )}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await LyricsProvider(tmp_path, client).get_synced(
            TrackQuery("netease-key", "Tema", "Artista", "Álbum", 240_000)
        )

    assert result.provider == "NetEase"
    assert result.timing == "synced"
    assert result.lines == [
        {"time_ms": 12_400, "text": "Primera línea"},
        {"time_ms": 16_800, "text": "Segunda línea"},
    ]


@pytest.mark.asyncio
async def test_netease_is_skipped_when_the_recording_does_not_match(tmp_path, monkeypatch):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("lyrics.asyncio.sleep", no_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "lrclib.net" and request.url.path == "/api/get":
            return httpx.Response(404, json={"code": 404})
        if request.url.host == "lrclib.net":
            return httpx.Response(200, json=[])
        if request.url.host == "api.amll.dev":
            return httpx.Response(200, json={"data": {"items": []}})
        if request.url.path == "/api/cloudsearch/pc":
            return httpx.Response(200, json={"result": {"songs": [{
                "id": 42,
                "name": "Tema",
                "dt": 320_000,
                "ar": [{"name": "Artista"}],
            }]}})
        raise AssertionError("no debe pedirse la letra de una grabación distinta")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await LyricsProvider(tmp_path, client).get_synced(
            TrackQuery("netease-mismatch", "Tema", "Artista", "Álbum", 240_000)
        )

    assert result.lines == []

def test_embedded_chinese_translation_is_removed_from_netease_lyrics():
    lines = [
        {"time_ms": 26_084, "text": "Sola, ilusionada me quedé"},
        {"time_ms": 27_085, "text": "只留下一个满怀期待的我"},
        {"time_ms": 37_153, "text": "Creyendo que tú me amabas también"},
        {"time_ms": 38_153, "text": "曾以为你真心爱我"},
        {"time_ms": 46_775, "text": "Lo que tuvimos ya se acabó"},
        {"time_ms": 47_775, "text": "我们之间的一切早已落幕"},
    ]
    assert [line["text"] for line in strip_embedded_translations(lines)] == [
        "Sola, ilusionada me quedé",
        "Creyendo que tú me amabas también",
        "Lo que tuvimos ya se acabó",
    ]


def test_bilingual_songs_keep_both_scripts():
    # Las líneas japonesas e inglesas alternan con separación real de canción,
    # no pegadas como una traducción sintética.
    lines = [
        {"time_ms": 12_800, "text": "嗄れた夜白い月が"},
        {"time_ms": 15_740, "text": "照らす月明り"},
        {"time_ms": 18_440, "text": "Let it burn away"},
        {"time_ms": 21_550, "text": "無情に過ぎ行く"},
        {"time_ms": 24_420, "text": "閉じたその瞳の中"},
        {"time_ms": 27_360, "text": "I can't see"},
    ]
    assert strip_embedded_translations(lines) == lines


def test_stripping_never_empties_the_lyrics():
    lines = [
        {"time_ms": 1_000, "text": "One"},
        {"time_ms": 1_500, "text": "一"},
        {"time_ms": 2_000, "text": "二"},
        {"time_ms": 2_500, "text": "三"},
    ]
    assert strip_embedded_translations(lines)
