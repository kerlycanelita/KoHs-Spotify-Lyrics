from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import httpx

from lyrics import TrackQuery, normalize_text


logger = logging.getLogger(__name__)


def _image_extension(content_type: str, content: bytes) -> str:
    content_type = content_type.lower()
    if "png" in content_type or content.startswith(b"\x89PNG"):
        return ".png"
    if "webp" in content_type or content.startswith(b"RIFF"):
        return ".webp"
    return ".jpg"


class ArtworkProvider:
    NEGATIVE_CACHE_SECONDS = 24 * 60 * 60
    MAX_IMAGE_BYTES = 15 * 1024 * 1024
    MAX_DURATION_DELTA_SECONDS = 15.0
    DEEZER_COVER_FIELDS = ("cover_xl", "cover_big", "cover_medium")

    def __init__(self, cache_dir: Path, client: httpx.AsyncClient):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = client
        self._musicbrainz_lock = asyncio.Lock()
        self._last_musicbrainz_request = 0.0

    async def save_windows_fallback(
        self, query: TrackQuery, content: bytes | None
    ) -> str | None:
        if not content:
            return self._find_cached(query, "windows")
        extension = _image_extension("", content)
        path = self.cache_dir / f"{query.key}-windows{extension}"
        if not path.exists():
            try:
                await asyncio.to_thread(path.write_bytes, content)
            except OSError:
                logger.exception("No se pudo guardar la portada de Windows")
                return None
        return f"/artwork/{path.name}"

    async def resolve_high_resolution(self, query: TrackQuery) -> str | None:
        cached = self._find_cached(query, "highres")
        if cached:
            return cached

        # v3 invalidates old misses now that Deezer leads the provider chain.
        missing_marker = self.cache_dir / f"{query.key}-highres-v3.none"
        try:
            if (
                missing_marker.exists()
                and time.time() - missing_marker.stat().st_mtime < self.NEGATIVE_CACHE_SECONDS
            ):
                return None
        except OSError:
            pass

        if not query.artist or not query.title:
            self._mark_missing(missing_marker)
            return None

        # iTunes serves up to 3000x3000, Deezer answers 1000x1000 in a single
        # request when Apple has no match, and MusicBrainz plus Cover Art Archive
        # goes last because it needs two hops and one request per second.
        image_url = None
        for name, lookup in (
            ("iTunes", self._find_itunes_cover_url),
            ("Deezer", self._find_deezer_cover_url),
            ("MusicBrainz", self._find_musicbrainz_cover_url),
        ):
            try:
                image_url = await lookup(query)
            except (httpx.HTTPError, ValueError, TypeError):
                logger.warning(
                    "%s no pudo localizar la portada de %s — %s",
                    name,
                    query.artist,
                    query.title,
                    exc_info=True,
                )
                continue
            if image_url:
                logger.debug("Portada de %s resuelta por %s", query.title, name)
                break

        if not image_url:
            self._mark_missing(missing_marker)
            return None
        try:
            return await self._download(query, image_url)
        except httpx.HTTPError:
            logger.exception("No se pudo descargar la portada de %s", query.title)
            return None

    async def _find_deezer_cover_url(self, query: TrackQuery) -> str | None:
        term = (
            f'artist:"{self._plain_term(query.artist)}" '
            f'track:"{self._plain_term(query.title)}"'
        )
        response = await self.client.get(
            "https://api.deezer.com/search", params={"q": term, "limit": 15}
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("error"):
            return None
        results = payload.get("data", [])
        if not isinstance(results, list):
            return None

        wanted_title = normalize_text(query.title)
        wanted_artist = normalize_text(query.artist)
        wanted_album = normalize_text(query.album)
        duration_seconds = query.duration_ms / 1000 if query.duration_ms >= 1000 else 0
        ranked: list[tuple[float, str]] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            artist = item.get("artist") if isinstance(item.get("artist"), dict) else {}
            album = item.get("album") if isinstance(item.get("album"), dict) else {}
            if normalize_text(str(artist.get("name") or "")) != wanted_artist:
                continue
            if normalize_text(str(item.get("title") or "")) != wanted_title:
                continue
            score = 60.0
            if wanted_album and normalize_text(str(album.get("title") or "")) == wanted_album:
                score += 45
            if duration_seconds:
                try:
                    delta = abs(float(item.get("duration") or 0) - duration_seconds)
                except (TypeError, ValueError):
                    continue
                # A different recording with the same name (live, remix) would
                # bring the wrong cover, so keep only close durations.
                if delta > self.MAX_DURATION_DELTA_SECONDS:
                    continue
                score -= delta
            for field in self.DEEZER_COVER_FIELDS:
                candidate = album.get(field)
                if isinstance(candidate, str) and candidate.startswith("https://"):
                    ranked.append((score, candidate))
                    break
        return max(ranked, key=lambda item: item[0])[1] if ranked else None

    async def _find_musicbrainz_cover_url(self, query: TrackQuery) -> str | None:
        if not query.album:
            return None
        release_group_id = await self._find_release_group(query)
        return await self._find_cover_url(release_group_id) if release_group_id else None

    async def _find_release_group(self, query: TrackQuery) -> str | None:
        escaped_album = self._escape_query(query.album)
        escaped_artist = self._escape_query(query.artist)
        lucene_query = f'releasegroup:"{escaped_album}" AND artist:"{escaped_artist}"'

        async with self._musicbrainz_lock:
            wait_for = 1.05 - (time.monotonic() - self._last_musicbrainz_request)
            if wait_for > 0:
                await asyncio.sleep(wait_for)
            response = await self.client.get(
                "https://musicbrainz.org/ws/2/release-group/",
                params={"query": lucene_query, "fmt": "json", "limit": 6},
            )
            self._last_musicbrainz_request = time.monotonic()

        response.raise_for_status()
        payload = response.json()
        groups = payload.get("release-groups", []) if isinstance(payload, dict) else []
        wanted_album = normalize_text(query.album)
        wanted_artist = normalize_text(query.artist)
        ranked: list[tuple[float, str]] = []
        for group in groups:
            if not isinstance(group, dict) or not group.get("id"):
                continue
            api_score = float(group.get("score") or 0)
            title = normalize_text(str(group.get("title") or ""))
            artists = " ".join(
                normalize_text(str(credit.get("name") or ""))
                for credit in group.get("artist-credit", [])
                if isinstance(credit, dict)
            )
            score = api_score
            if title == wanted_album:
                score += 60
            if wanted_artist and wanted_artist in artists:
                score += 35
            if str(group.get("primary-type") or "").lower() in {"album", "ep", "single"}:
                score += 5
            ranked.append((score, str(group["id"])))
        if not ranked:
            return None
        score, release_group_id = max(ranked, key=lambda item: item[0])
        return release_group_id if score >= 120 else None

    async def _find_cover_url(self, release_group_id: str) -> str | None:
        response = await self.client.get(
            f"https://coverartarchive.org/release-group/{release_group_id}",
            follow_redirects=True,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        images = payload.get("images", []) if isinstance(payload, dict) else []
        front_images = [image for image in images if isinstance(image, dict) and image.get("front")]
        candidates = front_images or [image for image in images if isinstance(image, dict)]
        for image in candidates:
            original = image.get("image")
            if isinstance(original, str) and original.startswith("https://"):
                return original
            thumbnails = image.get("thumbnails", {})
            if isinstance(thumbnails, dict):
                for size in ("1200", "large", "500", "small"):
                    candidate = thumbnails.get(size)
                    if isinstance(candidate, str) and candidate.startswith("https://"):
                        return candidate
        return None

    async def _find_itunes_cover_url(self, query: TrackQuery) -> str | None:
        searches = [
            ("song", f"{query.artist} {query.title}"),
            ("album", f"{query.artist} {query.album}"),
        ]
        wanted_title = normalize_text(query.title)
        wanted_artist = normalize_text(query.artist)
        wanted_album = normalize_text(query.album)
        ranked: list[tuple[int, str]] = []
        for entity, term in searches:
            response = await self.client.get(
                "https://itunes.apple.com/search",
                params={"term": term, "entity": entity, "limit": 20},
            )
            response.raise_for_status()
            payload = response.json()
            results = payload.get("results", []) if isinstance(payload, dict) else []
            for item in results:
                if not isinstance(item, dict):
                    continue
                artist = normalize_text(str(item.get("artistName") or ""))
                if not wanted_artist or artist != wanted_artist:
                    continue
                title = normalize_text(str(item.get("trackName") or ""))
                album = normalize_text(str(item.get("collectionName") or ""))
                score = 40
                if wanted_title and title == wanted_title:
                    score += 80
                if wanted_album and album == wanted_album:
                    score += 55
                artwork_url = item.get("artworkUrl100")
                if (
                    score < 90
                    or not isinstance(artwork_url, str)
                    or not artwork_url.startswith("https://")
                ):
                    continue
                # Apple serves any requested size up to the master file;
                # 3000x3000 is the largest value the thumbnailer still accepts.
                high_resolution = re.sub(
                    r"/\d+x\d+bb\.", "/3000x3000bb.", artwork_url
                )
                ranked.append((score, high_resolution))
            if ranked:
                break
        return max(ranked, key=lambda item: item[0])[1] if ranked else None

    async def _download(self, query: TrackQuery, image_url: str) -> str | None:
        response = await self.client.get(image_url, follow_redirects=True)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        content_length = int(response.headers.get("content-length", 0) or 0)
        if "image/" not in content_type.lower() or content_length > self.MAX_IMAGE_BYTES:
            return None
        content = response.content
        if not content or len(content) > self.MAX_IMAGE_BYTES:
            return None
        extension = _image_extension(content_type, content)
        path = self.cache_dir / f"{query.key}-highres{extension}"
        await asyncio.to_thread(path.write_bytes, content)
        return f"/artwork/{path.name}"

    def _find_cached(self, query: TrackQuery, kind: str) -> str | None:
        for extension in (".jpg", ".png", ".webp"):
            path = self.cache_dir / f"{query.key}-{kind}{extension}"
            if path.exists():
                return f"/artwork/{path.name}"
        return None

    @staticmethod
    def _plain_term(value: str) -> str:
        """Strip the characters that would break Deezer's advanced search syntax."""
        return value.replace('"', " ").replace("\\", " ").strip()

    @staticmethod
    def _escape_query(value: str) -> str:
        return re.sub(r'([+\-&|!(){}\[\]^"~*?:\\/])', r"\\\1", value)

    @staticmethod
    def _mark_missing(path: Path) -> None:
        try:
            path.write_text(json.dumps({"missing": True, "at": time.time()}), encoding="utf-8")
        except OSError:
            logger.exception("No se pudo guardar el estado de portada ausente")
