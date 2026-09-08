from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from pathlib import Path

import httpx


logger = logging.getLogger(__name__)

IMPORT_URL = re.compile(r'@import\s+url\(["\'](?P<url>https://fonts\.googleapis\.com/[^"\']+)["\']\)\s*;')
FONT_URL = re.compile(r"https://fonts\.gstatic\.com/[^)'\"\s]+\.woff2")
ASSET_NAME = re.compile(r"^[0-9a-f]{24}\.woff2$")
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)


class LocalFontCatalog:
    """Cache Google Fonts behind the overlay's own origin.

    TikTok LIVE Studio may block fonts.googleapis.com/fonts.gstatic.com or keep
    their responses cached independently from the browser source.  Serving the
    rewritten CSS and WOFF2 files through the existing tunnel avoids that
    renderer-specific external dependency.
    """

    MAX_FONT_BYTES = 5 * 1024 * 1024

    def __init__(self, cache_dir: Path, source_css: Path):
        self.cache_dir = cache_dir
        self.source_css = source_css
        self.catalog_path = cache_dir / "catalog.css"
        self.manifest_path = cache_dir / "manifest.json"
        self._sources: dict[str, str] = {}
        self._asset_locks: dict[str, asyncio.Lock] = {}

    async def prepare(self, client: httpx.AsyncClient) -> bool:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        source = self.source_css.read_text(encoding="utf-8")
        source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        if self._load_manifest(source_hash) and self.catalog_path.exists():
            return True

        urls = [match.group("url") for match in IMPORT_URL.finditer(source)]
        if not urls:
            logger.error("El catálogo de fuentes no contiene imports válidos")
            return False

        try:
            responses = await asyncio.gather(
                *(client.get(url, headers={"User-Agent": BROWSER_USER_AGENT}) for url in urls)
            )
            for response in responses:
                response.raise_for_status()
            combined = "\n\n".join(response.text for response in responses)
        except httpx.HTTPError:
            logger.exception("No se pudo actualizar el catálogo local de fuentes")
            return self.catalog_path.exists() and self._load_manifest(None)

        sources: dict[str, str] = {}
        for remote_url in sorted(set(FONT_URL.findall(combined))):
            filename = f"{hashlib.sha256(remote_url.encode('utf-8')).hexdigest()[:24]}.woff2"
            sources[filename] = remote_url
            combined = combined.replace(remote_url, f"/font-assets/{filename}")

        if not sources:
            logger.error("Google Fonts no devolvió archivos WOFF2")
            return False

        self._atomic_write_text(self.catalog_path, combined + "\n")
        self._atomic_write_text(
            self.manifest_path,
            json.dumps(
                {"source_hash": source_hash, "assets": sources},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )
        self._sources = sources
        logger.info("Catálogo local preparado: %d archivos de fuente disponibles", len(sources))
        return True

    async def asset_path(
        self, filename: str, client: httpx.AsyncClient
    ) -> Path | None:
        if not ASSET_NAME.fullmatch(filename):
            return None
        remote_url = self._sources.get(filename)
        if not remote_url:
            return None
        path = self.cache_dir / filename
        if path.exists() and path.stat().st_size > 0:
            return path

        lock = self._asset_locks.setdefault(filename, asyncio.Lock())
        async with lock:
            if path.exists() and path.stat().st_size > 0:
                return path
            try:
                response = await client.get(
                    remote_url,
                    headers={"User-Agent": BROWSER_USER_AGENT},
                )
                response.raise_for_status()
                content = response.content
            except httpx.HTTPError:
                logger.exception("No se pudo descargar la fuente %s", filename)
                return None
            if not content.startswith(b"wOF2") or len(content) > self.MAX_FONT_BYTES:
                logger.error("Archivo de fuente inválido: %s", filename)
                return None
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(content)
            os.replace(temporary, path)
            return path

    def _load_manifest(self, source_hash: str | None) -> bool:
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            if source_hash is not None and payload.get("source_hash") != source_hash:
                return False
            assets = payload.get("assets")
            if not isinstance(assets, dict):
                return False
            sources = {
                str(name): str(url)
                for name, url in assets.items()
                if ASSET_NAME.fullmatch(str(name)) and FONT_URL.fullmatch(str(url))
            }
            if not sources:
                return False
            self._sources = sources
            return True
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return False

    @staticmethod
    def _atomic_write_text(path: Path, value: str) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(value, encoding="utf-8")
        os.replace(temporary, path)
