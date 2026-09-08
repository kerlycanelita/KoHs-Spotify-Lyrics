from __future__ import annotations

import httpx
import pytest

from artwork import ArtworkProvider
from lyrics import TrackQuery


@pytest.mark.asyncio
async def test_cover_art_archive_redirect_is_followed(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "musicbrainz.org":
            return httpx.Response(
                200,
                json={
                    "release-groups": [
                        {
                            "id": "release-id",
                            "score": 100,
                            "title": "Album",
                            "primary-type": "Album",
                            "artist-credit": [{"name": "Artist"}],
                        }
                    ]
                },
            )
        if request.url.host == "coverartarchive.org":
            return httpx.Response(
                307,
                headers={"location": "https://archive.org/cover-index.json"},
            )
        if request.url.path.endswith("cover-index.json"):
            return httpx.Response(
                200,
                json={
                    "images": [
                        {"front": True, "image": "https://archive.org/front.jpg"}
                    ]
                },
            )
        return httpx.Response(
            200,
            content=b"\xff\xd8\xff\xe0" + b"image-data",
            headers={"content-type": "image/jpeg"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ArtworkProvider(tmp_path, client)
        result = await provider.resolve_high_resolution(
            TrackQuery("art-key", "Song", "Artist", "Album", 180_000)
        )

    assert result == "/artwork/art-key-highres.jpg"
    assert (tmp_path / "art-key-highres.jpg").exists()


@pytest.mark.asyncio
async def test_itunes_is_used_when_musicbrainz_has_no_cover(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "musicbrainz.org":
            return httpx.Response(200, json={"release-groups": []})
        if request.url.host == "itunes.apple.com":
            return httpx.Response(200, json={"results": [{
                "trackName": "Song",
                "artistName": "Artist",
                "collectionName": "Album",
                "artworkUrl100": "https://is1-ssl.mzstatic.com/cover/100x100bb.jpg",
            }]})
        return httpx.Response(
            200,
            content=b"\xff\xd8\xff\xe0" + b"itunes-image",
            headers={"content-type": "image/jpeg"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ArtworkProvider(tmp_path, client).resolve_high_resolution(
            TrackQuery("itunes-key", "Song", "Artist", "Album", 180_000)
        )

    assert result == "/artwork/itunes-key-highres.jpg"
    assert (tmp_path / "itunes-key-highres.jpg").exists()
