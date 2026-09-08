from __future__ import annotations

import httpx
import pytest

from font_assets import LocalFontCatalog


@pytest.mark.asyncio
async def test_font_catalog_rewrites_remote_files_to_same_origin(tmp_path):
    source = tmp_path / "source.css"
    source.write_text(
        '@import url("https://fonts.googleapis.com/css2?family=Test&display=swap");\n',
        encoding="utf-8",
    )
    remote_font = "https://fonts.gstatic.com/s/test/v1/test-latin.woff2"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "fonts.googleapis.com":
            return httpx.Response(
                200,
                text=(
                    "@font-face { font-family: 'Test'; "
                    f"src: url({remote_font}) format('woff2'); }}"
                ),
            )
        if request.url.host == "fonts.gstatic.com":
            return httpx.Response(200, content=b"wOF2font-data")
        return httpx.Response(404)

    catalog = LocalFontCatalog(tmp_path / "cache", source)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await catalog.prepare(client)
        local_css = catalog.catalog_path.read_text(encoding="utf-8")
        assert "fonts.gstatic.com" not in local_css
        assert "/font-assets/" in local_css
        filename = next(iter(catalog._sources))
        asset = await catalog.asset_path(filename, client)

    assert asset is not None
    assert asset.read_bytes() == b"wOF2font-data"


@pytest.mark.asyncio
async def test_font_catalog_rejects_unknown_or_unsafe_asset_names(tmp_path):
    source = tmp_path / "source.css"
    source.write_text("", encoding="utf-8")
    catalog = LocalFontCatalog(tmp_path / "cache", source)
    async with httpx.AsyncClient() as client:
        assert await catalog.asset_path("../secret.woff2", client) is None
        assert await catalog.asset_path("0" * 24 + ".woff2", client) is None
