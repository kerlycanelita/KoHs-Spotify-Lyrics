from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


logger = logging.getLogger(__name__)

LRC_LINE = re.compile(
    r"^(?P<timestamps>(?:\[(?:\d{1,3}):(?:\d{1,2})(?:[.:]\d{1,3})?\])+)(?P<text>.*)$"
)
LRC_TIMESTAMP = re.compile(r"\[(?P<minutes>\d{1,3}):(?P<seconds>\d{1,2})(?:[.:](?P<fraction>\d{1,3}))?\]")
MAX_DURATION_DELTA_SECONDS = 3.0
SYNC_END_GRACE_MS = 3_000
MIN_SYNCED_LINES = 2
# NetEase ships production credits inside the LRC itself; they carry real
# timestamps but are not lyrics, so they are dropped before validating.
NETEASE_CREDIT = re.compile(
    r"^(?:作词|作曲|编曲|制作人|出品人?|监制|策划|统筹|发行|录音|混音|母带|后期"
    r"|吉他|贝斯|鼓|键盘|弦乐|和声|演唱|词|曲"
    r"|Lyrics?|Music|Composed|Arranged|Produced|Written|Mixing|Mastering|Vocals?)"
    r"(?:\s+by)?\s*[:：]"
)


def normalize_text(value: str) -> str:
    """Normalize metadata without discarding non-Latin writing systems.

    The old ASCII-only normalization collapsed every Japanese title to an empty
    string.  Tracks by the same artist with a similar duration could therefore
    share a cache key, making the overlay reuse another song's artwork/lyrics.
    Latin accents remain insensitive (``canción`` == ``cancion``), while CJK
    and other Unicode letters are preserved.
    """
    folded = unicodedata.normalize("NFKC", value or "").casefold()
    pieces: list[str] = []
    for char in folded:
        if not char.isalnum():
            pieces.append(" ")
            continue
        decomposed = unicodedata.normalize("NFKD", char)
        ascii_equivalent = "".join(
            part for part in decomposed if part.isascii() and part.isalnum()
        )
        pieces.append(ascii_equivalent or char)
    return " ".join("".join(pieces).split())


def track_cache_key(title: str, artist: str, album: str, duration_ms: int) -> str:
    signature = "|".join(
        (
            normalize_text(artist),
            normalize_text(album),
            normalize_text(title),
            str(round(max(duration_ms, 0) / 1000)),
        )
    )
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()[:24]


def parse_lrc(value: str | None, duration_ms: int = 0) -> list[dict[str, Any]]:
    if not value or not isinstance(value, str):
        return []

    parsed: list[dict[str, Any]] = []
    for raw_line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        match = LRC_LINE.match(raw_line.strip("\ufeff"))
        if not match:
            continue
        text = match.group("text").strip()
        if not text:
            continue
        for timestamp in LRC_TIMESTAMP.finditer(match.group("timestamps")):
            minutes = int(timestamp.group("minutes"))
            seconds = int(timestamp.group("seconds"))
            if seconds >= 60:
                continue
            fraction = timestamp.group("fraction") or "0"
            milliseconds = int(fraction.ljust(3, "0")[:3])
            time_ms = (minutes * 60 + seconds) * 1000 + milliseconds
            if duration_ms > 0 and time_ms > duration_ms + SYNC_END_GRACE_MS:
                continue
            parsed.append({"time_ms": time_ms, "text": text})

    parsed.sort(key=lambda line: line["time_ms"])
    deduplicated: list[dict[str, Any]] = []
    for line in parsed:
        if deduplicated and line == deduplicated[-1]:
            continue
        deduplicated.append(line)
    return deduplicated


@dataclass(slots=True)
class TrackQuery:
    key: str
    title: str
    artist: str
    album: str
    duration_ms: int


@dataclass(slots=True)
class LyricsResult:
    lines: list[dict[str, Any]]
    provider: str = "LRCLIB"
    cached: bool = False
    timing: str = "synced"


def _ttml_time_ms(value: str | None) -> int | None:
    if not value:
        return None
    raw = value.strip().lower()
    try:
        if raw.endswith("ms"):
            return round(float(raw[:-2]) * 1_000 / 1_000)
        if raw.endswith("s"):
            return round(float(raw[:-1]) * 1_000)
        parts = raw.split(":")
        if len(parts) == 1:
            return round(float(parts[0]) * 1_000)
        if len(parts) == 2:
            return round((float(parts[0]) * 60 + float(parts[1])) * 1_000)
        if len(parts) == 3:
            return round(
                (float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2]))
                * 1_000
            )
    except ValueError:
        return None
    return None


def parse_ttml(value: str | None, duration_ms: int = 0) -> list[dict[str, Any]]:
    if not value:
        return []
    try:
        root = ET.fromstring(value)
    except ET.ParseError:
        return []

    def role(node: ET.Element) -> str:
        return next(
            (str(attribute) for key, attribute in node.attrib.items() if key.endswith("}role") or key == "role"),
            "",
        )

    def original_text(node: ET.Element) -> str:
        if role(node) in {"x-translation", "x-bg"}:
            return ""
        pieces = [node.text or ""]
        for child in node:
            pieces.append(original_text(child))
            pieces.append(child.tail or "")
        return "".join(pieces)

    lines: list[dict[str, Any]] = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] != "p":
            continue
        time_ms = _ttml_time_ms(node.attrib.get("begin"))
        text = " ".join(original_text(node).split())
        if time_ms is None or not text:
            continue
        if duration_ms > 0 and time_ms > duration_ms + SYNC_END_GRACE_MS:
            continue
        lines.append({"time_ms": time_ms, "text": text})
    lines.sort(key=lambda line: line["time_ms"])
    return lines


CJK_SCRIPT = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")
TRANSLATION_PAIR_WINDOW_MS = 1_500
TRANSLATION_PAIR_RATIO = 0.4


def _line_script(text: str) -> str:
    return "cjk" if CJK_SCRIPT.search(text) else "latin"


def strip_embedded_translations(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop the translation some contributors paste into the lyrics themselves.

    NetEase files often repeat every line in Chinese about a second after the
    original, so the overlay would alternate the real lyric with a translation
    that no setting can turn off.  Genuinely bilingual songs keep both scripts:
    their lines are not paired that tightly nor that consistently.
    """
    if len(lines) < 4:
        return lines
    scripts = [_line_script(str(line.get("text") or "")) for line in lines]
    if len(set(scripts)) < 2:
        return lines

    paired = {"cjk": 0, "latin": 0}
    for index in range(1, len(lines)):
        if scripts[index] == scripts[index - 1]:
            continue
        gap = int(lines[index]["time_ms"]) - int(lines[index - 1]["time_ms"])
        if 0 <= gap <= TRANSLATION_PAIR_WINDOW_MS:
            paired[scripts[index]] += 1

    threshold = len(lines) * TRANSLATION_PAIR_RATIO
    for script, count in paired.items():
        if count < threshold:
            continue
        kept = [line for line, own in zip(lines, scripts) if own != script]
        # Nunca vaciar la letra por culpa de la heurística.
        if len(kept) >= max(2, len(lines) // 4):
            return kept
    return lines


def has_valid_synced_timeline(lines: list[dict[str, Any]], duration_ms: int) -> bool:
    if len(lines) < MIN_SYNCED_LINES:
        return False
    try:
        timestamps = [int(line["time_ms"]) for line in lines]
    except (KeyError, TypeError, ValueError):
        return False
    if any(timestamp < 0 for timestamp in timestamps):
        return False
    if timestamps != sorted(timestamps) or len(set(timestamps)) < MIN_SYNCED_LINES:
        return False
    if duration_ms > 0 and timestamps[-1] > duration_ms + SYNC_END_GRACE_MS:
        return False
    return True


def lrclib_record_matches(query: TrackQuery, record: dict[str, Any]) -> bool:
    record_title = normalize_text(str(record.get("trackName") or record.get("name") or ""))
    record_artist = normalize_text(str(record.get("artistName") or ""))
    if record_title != normalize_text(query.title) or record_artist != normalize_text(query.artist):
        return False

    wanted_album = normalize_text(query.album)
    record_album = normalize_text(str(record.get("albumName") or ""))
    if wanted_album and record_album != wanted_album:
        return False

    if query.duration_ms >= 1000:
        try:
            record_duration = float(record.get("duration") or 0)
        except (TypeError, ValueError):
            return False
        if record_duration <= 0:
            return False
        if abs(record_duration - query.duration_ms / 1000) > MAX_DURATION_DELTA_SECONDS:
            return False
    return True


class LyricsProvider:
    NEGATIVE_CACHE_SECONDS = 6 * 60 * 60
    CACHE_VERSION = 6

    def __init__(
        self,
        cache_dir: Path,
        client: httpx.AsyncClient,
        musixmatch_api_key: str | None = None,
    ):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = client
        self.musixmatch_api_key = (musixmatch_api_key or "").strip() or None
        self._request_lock = asyncio.Lock()

    async def get_synced(self, query: TrackQuery) -> LyricsResult:
        cached = self._read_cache(query)
        if cached is not None:
            return cached

        stale_positive = self._read_stale_positive(query)
        operational_failure = False
        record: dict[str, Any] | None = None
        try:
            async with self._request_lock:
                record = await self._exact_lookup(query)
                if record and not lrclib_record_matches(query, record):
                    record = None
                exact_lines = parse_lrc(
                    record.get("syncedLyrics") if record else None,
                    query.duration_ms,
                )
                if not has_valid_synced_timeline(exact_lines, query.duration_ms):
                    await asyncio.sleep(0.25)
                    record = await self._search_lookup(query)
        except (httpx.HTTPError, ValueError, json.JSONDecodeError):
            operational_failure = True
            logger.exception("LRCLIB no está disponible para %s — %s", query.artist, query.title)

        synced = record.get("syncedLyrics") if record else None
        lines = parse_lrc(synced, query.duration_ms)
        if not has_valid_synced_timeline(lines, query.duration_ms):
            lines = []
        result = LyricsResult(lines=lines, provider="LRCLIB")

        if not result.lines:
            try:
                async with self._request_lock:
                    await asyncio.sleep(0.15)
                    result = await self._amll_lookup(query)
            except (httpx.HTTPError, ValueError, ET.ParseError, json.JSONDecodeError):
                operational_failure = True
                logger.exception(
                    "AMLL no está disponible para %s — %s", query.artist, query.title
                )

        if not result.lines:
            try:
                async with self._request_lock:
                    await asyncio.sleep(0.15)
                    result = await self._netease_lookup(query)
            except (httpx.HTTPError, ValueError, json.JSONDecodeError):
                operational_failure = True
                logger.exception(
                    "NetEase no está disponible para %s — %s", query.artist, query.title
                )

        if not result.lines and self.musixmatch_api_key:
            try:
                async with self._request_lock:
                    await asyncio.sleep(0.25)
                    result = await self._musixmatch_lookup(query)
            except (httpx.HTTPError, ValueError, json.JSONDecodeError):
                operational_failure = True
                logger.exception(
                    "Musixmatch no está disponible para %s — %s",
                    query.artist,
                    query.title,
                )

        if not result.lines and operational_failure and stale_positive is not None:
            return stale_positive
        self._write_cache(query, result)
        return result

    async def _exact_lookup(self, query: TrackQuery) -> dict[str, Any] | None:
        params: dict[str, str | int] = {
            "track_name": query.title,
            "artist_name": query.artist,
        }
        if query.album:
            params["album_name"] = query.album
        if query.duration_ms >= 1000:
            params["duration"] = round(query.duration_ms / 1000)

        response = await self.client.get("https://lrclib.net/api/get", params=params)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else None

    async def _search_lookup(self, query: TrackQuery) -> dict[str, Any] | None:
        response = await self.client.get(
            "https://lrclib.net/api/search",
            params={"track_name": query.title, "artist_name": query.artist},
        )
        response.raise_for_status()
        records = response.json()
        if not isinstance(records, list):
            return None

        duration_seconds = query.duration_ms / 1000
        candidates: list[tuple[float, dict[str, Any]]] = []
        for record in records:
            if not isinstance(record, dict) or not record.get("syncedLyrics"):
                continue
            if not lrclib_record_matches(query, record):
                continue
            record_duration = float(record.get("duration") or 0)
            duration_delta = abs(record_duration - duration_seconds) if duration_seconds else 0
            score = 100 - duration_delta * 10
            candidates.append((score, record))

        return max(candidates, key=lambda item: item[0])[1] if candidates else None

    async def _amll_lookup(self, query: TrackQuery) -> LyricsResult:
        response = await self.client.get(
            "https://api.amll.dev/v1/lyrics/search",
            params={
                "musicName": query.title,
                "artistName": query.artist,
                "pageSize": 10,
            },
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        items = data.get("items", []) if isinstance(data, dict) else []
        if not isinstance(items, list):
            return LyricsResult(lines=[], provider="AMLL")

        wanted_title = normalize_text(query.title)
        wanted_artist = normalize_text(query.artist)
        wanted_album = normalize_text(query.album)
        candidates: list[tuple[int, dict[str, Any]]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            titles = [normalize_text(str(value)) for value in item.get("musicNames", [])]
            artists = [normalize_text(str(value)) for value in item.get("artistNames", [])]
            if wanted_title not in titles or wanted_artist not in artists:
                continue
            albums = [normalize_text(str(value)) for value in item.get("albumNames", [])]
            if wanted_album and wanted_album not in albums:
                continue
            candidates.append((10 if wanted_album else 0, item))
        if not candidates:
            return LyricsResult(lines=[], provider="AMLL")

        selected = max(candidates, key=lambda candidate: candidate[0])[1]
        lyric_id = selected.get("id")
        if lyric_id is None:
            return LyricsResult(lines=[], provider="AMLL")
        response = await self.client.get(
            "https://api.amll.dev/v1/lyrics/get", params={"id": lyric_id}
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        ttml = data.get("lyrics") if isinstance(data, dict) else None
        lines = parse_ttml(ttml, query.duration_ms)
        if not has_valid_synced_timeline(lines, query.duration_ms):
            lines = []
        return LyricsResult(lines=lines, provider="AMLL")

    async def _netease_lookup(self, query: TrackQuery) -> LyricsResult:
        """NetEase covers Japanese, doujin and Asian catalogues LRCLIB lacks.

        ``cloudsearch/pc`` is used instead of the older ``search/get``: the
        latter silently degrades to fuzzy results when several queries arrive
        from the same address, dropping the exact recording from the response.
        """
        response = await self.client.get(
            "https://music.163.com/api/cloudsearch/pc",
            params={
                "s": f"{query.title} {query.artist}",
                "type": 1,
                "offset": 0,
                "limit": 10,
            },
        )
        response.raise_for_status()
        payload = response.json()
        container = payload.get("result", {}) if isinstance(payload, dict) else {}
        songs = container.get("songs", []) if isinstance(container, dict) else []
        if not isinstance(songs, list):
            return LyricsResult(lines=[], provider="NetEase")

        wanted_title = normalize_text(query.title)
        wanted_artist = normalize_text(query.artist)
        duration_seconds = query.duration_ms / 1000 if query.duration_ms >= 1000 else 0
        candidates: list[tuple[float, int]] = []
        for song in songs:
            if not isinstance(song, dict) or song.get("id") is None:
                continue
            if normalize_text(str(song.get("name") or "")) != wanted_title:
                continue
            # cloudsearch names the fields ``ar``/``dt``; the legacy shape is
            # accepted too so a change of endpoint cannot silently break here.
            credits = song.get("ar") or song.get("artists") or []
            artists = [
                normalize_text(str(artist.get("name") or ""))
                for artist in credits
                if isinstance(artist, dict)
            ]
            if wanted_artist not in artists:
                continue
            score = 100.0
            if duration_seconds:
                try:
                    milliseconds = float(song.get("dt") or song.get("duration") or 0)
                except (TypeError, ValueError):
                    continue
                delta = abs(milliseconds / 1000 - duration_seconds)
                if delta > MAX_DURATION_DELTA_SECONDS:
                    continue
                score -= delta
            candidates.append((score, int(song["id"])))
        if not candidates:
            return LyricsResult(lines=[], provider="NetEase")

        song_id = max(candidates, key=lambda candidate: candidate[0])[1]
        response = await self.client.get(
            "https://music.163.com/api/song/lyric",
            params={"id": song_id, "lv": 1, "kv": 1, "tv": -1},
        )
        response.raise_for_status()
        payload = response.json()
        lrc = payload.get("lrc", {}) if isinstance(payload, dict) else {}
        raw = lrc.get("lyric") if isinstance(lrc, dict) else None
        lines = strip_embedded_translations([
            line
            for line in parse_lrc(raw, query.duration_ms)
            if not NETEASE_CREDIT.match(line["text"])
        ])
        if not has_valid_synced_timeline(lines, query.duration_ms):
            lines = []
        return LyricsResult(lines=lines, provider="NetEase")

    async def _musixmatch_lookup(self, query: TrackQuery) -> LyricsResult:
        params: dict[str, str | int] = {
            "apikey": self.musixmatch_api_key or "",
            "q_track": query.title,
            "q_artist": query.artist,
            "subtitle_format": "lrc",
        }
        if query.album:
            params["q_album"] = query.album
        if query.duration_ms >= 1000:
            params["f_subtitle_length"] = round(query.duration_ms / 1000)
            params["f_subtitle_length_max_deviation"] = 3
        response = await self.client.get(
            "https://api.musixmatch.com/ws/1.1/matcher.subtitle.get",
            params=params,
        )
        response.raise_for_status()
        payload = response.json()
        message = payload.get("message", {}) if isinstance(payload, dict) else {}
        header = message.get("header", {}) if isinstance(message, dict) else {}
        status_code = int(header.get("status_code") or 0)
        if status_code in {401, 402, 403}:
            raise ValueError("Musixmatch rechazó la API key o el plan no permite subtítulos")
        if status_code == 404:
            return LyricsResult(lines=[], provider="Musixmatch")
        body = message.get("body", {}) if isinstance(message, dict) else {}
        subtitle = body.get("subtitle", {}) if isinstance(body, dict) else {}
        synced = subtitle.get("subtitle_body") if isinstance(subtitle, dict) else None
        lines = parse_lrc(synced, query.duration_ms)
        if not has_valid_synced_timeline(lines, query.duration_ms):
            lines = []
        return LyricsResult(lines=lines, provider="Musixmatch")

    def _cache_path(self, query: TrackQuery) -> Path:
        return self.cache_dir / f"{query.key}.json"

    def _read_cache(self, query: TrackQuery) -> LyricsResult | None:
        path = self._cache_path(query)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not self._cache_matches_query(payload, query):
                return None
            lines = payload.get("lines")
            if not isinstance(lines, list):
                return None
            current_version = payload.get("cache_version") == self.CACHE_VERSION
            synced_timing = str(payload.get("timing") or "synced") == "synced"
            if lines and current_version and synced_timing and has_valid_synced_timeline(lines, query.duration_ms):
                return LyricsResult(
                    lines=lines,
                    provider=str(payload.get("provider") or "LRCLIB"),
                    cached=True,
                    timing=str(payload.get("timing") or "synced"),
                )
            same_provider_set = bool(payload.get("musixmatch_enabled")) == bool(
                self.musixmatch_api_key
            )
            if (
                payload.get("cache_version") == self.CACHE_VERSION
                and same_provider_set
                and time.time() < float(payload.get("expires_at", 0))
            ):
                return LyricsResult(lines=[], cached=True)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None
        return None

    def _read_stale_positive(self, query: TrackQuery) -> LyricsResult | None:
        path = self._cache_path(query)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not self._cache_matches_query(payload, query):
                return None
            lines = payload.get("lines")
            if (
                payload.get("cache_version") == self.CACHE_VERSION
                and str(payload.get("timing") or "synced") == "synced"
                and isinstance(lines, list)
                and has_valid_synced_timeline(lines, query.duration_ms)
            ):
                return LyricsResult(
                    lines=lines,
                    provider=str(payload.get("provider") or "LRCLIB"),
                    cached=True,
                    timing=str(payload.get("timing") or "synced"),
                )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
        return None

    @staticmethod
    def _cache_matches_query(payload: dict[str, Any], query: TrackQuery) -> bool:
        cached_track = payload.get("track")
        if not isinstance(cached_track, dict):
            return False
        if normalize_text(str(cached_track.get("title") or "")) != normalize_text(query.title):
            return False
        if normalize_text(str(cached_track.get("artist") or "")) != normalize_text(query.artist):
            return False
        cached_album = normalize_text(str(cached_track.get("album") or ""))
        wanted_album = normalize_text(query.album)
        if cached_album and wanted_album and cached_album != wanted_album:
            return False
        try:
            cached_duration = int(cached_track.get("duration_ms") or 0)
        except (TypeError, ValueError):
            return False
        return not cached_duration or not query.duration_ms or abs(cached_duration - query.duration_ms) <= 2_000

    def _write_cache(self, query: TrackQuery, result: LyricsResult) -> None:
        payload = {
            "cache_version": self.CACHE_VERSION,
            "key": query.key,
            "track": {
                "title": query.title,
                "artist": query.artist,
                "album": query.album,
                "duration_ms": query.duration_ms,
            },
            "provider": result.provider,
            "timing": result.timing,
            "musixmatch_enabled": bool(self.musixmatch_api_key),
            "lines": result.lines,
            "created_at": time.time(),
            "expires_at": time.time() + self.NEGATIVE_CACHE_SECONDS if not result.lines else None,
        }
        path = self._cache_path(query)
        temporary = path.with_suffix(".tmp")
        try:
            temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            temporary.replace(path)
        except OSError:
            logger.exception("No se pudo guardar la caché de letra %s", path)
