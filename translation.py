from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from lyrics import TrackQuery


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TranslationResult:
    texts: list[str]
    provider: str | None = None
    cached: bool = False


@dataclass(slots=True)
class BatchTranslation:
    texts: list[str]
    provider: str


class TranslationProvider:
    API_URL = "https://api.mymemory.translated.net/get"
    GOOGLE_FALLBACK_URL = "https://translate.googleapis.com/translate_a/single"
    GOOGLE_SECONDARY_URL = "https://clients5.google.com/translate_a/t"
    CACHE_VERSION = 3
    MAX_BATCH_BYTES = 460
    MAX_GOOGLE_BATCH_BYTES = 2200
    RETRY_EMPTY_SECONDS = 5 * 60

    def __init__(self, cache_dir: Path, client: httpx.AsyncClient):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = client
        self.email = os.environ.get("MYMEMORY_EMAIL", "").strip() or None
        self._semaphore = asyncio.Semaphore(2)
        self._google_semaphore = asyncio.Semaphore(1)
        self._last_google_request = 0.0
        self._mymemory_unavailable_until = 0.0
        self._google_primary_unavailable_until = 0.0

    async def translate_lines(
        self,
        query: TrackQuery,
        lines: list[dict],
        target_language: str = "es",
    ) -> TranslationResult:
        source_texts = [str(line.get("text") or "").strip() for line in lines]
        cached = self._read_cache(query, source_texts, target_language)
        if cached is not None:
            return cached
        if not source_texts:
            return TranslationResult([])

        translations = ["" for _ in source_texts]
        if time.monotonic() < self._mymemory_unavailable_until:
            batches = self._build_batches(
                source_texts,
                max_bytes=self.MAX_GOOGLE_BATCH_BYTES,
            )
            results = await asyncio.gather(
                *(
                    self._google_result(texts, target_language)
                    for _, texts in batches
                ),
                return_exceptions=True,
            )
        else:
            batches = self._build_batches(source_texts)
            first_result = await self._translate_batch(batches[0][1], target_language)
            if (
                first_result.provider == "Google (respaldo)"
                and time.monotonic() < self._mymemory_unavailable_until
            ):
                first_indices, first_texts = batches[0]
                remaining_start = len(first_indices)
                batches = [(first_indices, first_texts)] + self._build_batches(
                    source_texts[remaining_start:],
                    max_bytes=self.MAX_GOOGLE_BATCH_BYTES,
                    index_offset=remaining_start,
                )
                remaining_results = await asyncio.gather(
                    *(
                        self._google_result(texts, target_language)
                        for _, texts in batches[1:]
                    ),
                    return_exceptions=True,
                )
                results = [first_result, *remaining_results]
            else:
                remaining_results = await asyncio.gather(
                    *(
                        self._translate_batch(texts, target_language)
                        for _, texts in batches[1:]
                    ),
                    return_exceptions=True,
                )
                results = [first_result, *remaining_results]
        providers: list[str] = []
        for (indices, texts), result in zip(batches, results, strict=True):
            if isinstance(result, BaseException):
                logger.warning(
                    "No se pudo traducir un bloque de %s: %s",
                    query.title,
                    result,
                )
                continue
            if len(result.texts) != len(indices):
                result = await self._translate_individually(texts, target_language)
            if result.provider not in providers:
                providers.append(result.provider)
            for index, translated in zip(indices, result.texts, strict=False):
                translations[index] = translated.strip()

        provider = " + ".join(providers) if any(translations) else None
        translated = TranslationResult(translations, provider=provider)
        self._write_cache(query, source_texts, target_language, translated)
        return translated

    def _build_batches(
        self,
        texts: list[str],
        *,
        max_bytes: int | None = None,
        index_offset: int = 0,
    ) -> list[tuple[list[int], list[str]]]:
        byte_limit = max_bytes or self.MAX_BATCH_BYTES
        batches: list[tuple[list[int], list[str]]] = []
        indices: list[int] = []
        values: list[str] = []
        size = 0
        for local_index, text in enumerate(texts):
            index = local_index + index_offset
            encoded_size = len(text.encode("utf-8"))
            if values and size + 1 + encoded_size > byte_limit:
                batches.append((indices, values))
                indices, values, size = [], [], 0
            if encoded_size > byte_limit:
                text = text.encode("utf-8")[:byte_limit].decode("utf-8", "ignore")
                encoded_size = len(text.encode("utf-8"))
            indices.append(index)
            values.append(text)
            size += encoded_size + (1 if len(values) > 1 else 0)
        if values:
            batches.append((indices, values))
        return batches

    async def _google_result(
        self, texts: list[str], target_language: str
    ) -> BatchTranslation:
        return BatchTranslation(
            await self._translate_google_batch(texts, target_language),
            "Google (respaldo)",
        )

    async def _translate_batch(
        self, texts: list[str], target_language: str
    ) -> BatchTranslation:
        try:
            return BatchTranslation(
                await self._translate_mymemory_batch(texts, target_language),
                "MyMemory",
            )
        except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError) as error:
            logger.info("MyMemory no disponible (%s); usando respaldo de Google", error)
            return BatchTranslation(
                await self._translate_google_batch(texts, target_language),
                "Google (respaldo)",
            )

    async def _translate_mymemory_batch(
        self, texts: list[str], target_language: str
    ) -> list[str]:
        if time.monotonic() < self._mymemory_unavailable_until:
            raise ValueError("cuota de MyMemory temporalmente agotada")
        params = {
            "q": "\n".join(texts),
            "langpair": f"autodetect|{target_language}",
            "mt": 1,
        }
        if self.email:
            params["de"] = self.email
        async with self._semaphore:
            response = await self.client.get(self.API_URL, params=params)
        if response.status_code == 429:
            self._mymemory_unavailable_until = time.monotonic() + 15 * 60
        response.raise_for_status()
        payload = response.json()
        details = str(payload.get("responseDetails") or "")
        if "TWO DISTINCT LANGUAGES" in details.upper():
            return texts.copy()
        if int(payload.get("responseStatus") or response.status_code) != 200:
            raise ValueError(details or "MyMemory rechazó la traducción")
        response_data = payload.get("responseData")
        if not isinstance(response_data, dict):
            raise ValueError("Respuesta de traducción inválida")
        translated = html.unescape(str(response_data.get("translatedText") or ""))
        return translated.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    async def _translate_google_batch(
        self, texts: list[str], target_language: str
    ) -> list[str]:
        request_variants = []
        if time.monotonic() >= self._google_primary_unavailable_until:
            request_variants.append(
                (
                    self.GOOGLE_FALLBACK_URL,
                    {
                        "client": "gtx",
                        "sl": "auto",
                        "tl": target_language,
                        "dt": "t",
                        "q": "\n".join(texts),
                    },
                )
            )
        request_variants.append(
            (
                self.GOOGLE_SECONDARY_URL,
                {
                    "client": "dict-chrome-ex",
                    "sl": "auto",
                    "tl": target_language,
                    "q": "\n".join(texts),
                },
            )
        )
        last_error: Exception | None = None
        async with self._google_semaphore:
            since_last_request = time.monotonic() - self._last_google_request
            if since_last_request < 0.65:
                await asyncio.sleep(0.65 - since_last_request)
            for url, params in request_variants:
                response = await self.client.get(url, params=params)
                self._last_google_request = time.monotonic()
                if response.status_code == 429:
                    if url == self.GOOGLE_FALLBACK_URL:
                        self._google_primary_unavailable_until = time.monotonic() + 15 * 60
                    last_error = httpx.HTTPStatusError(
                        "Google limitó temporalmente la traducción",
                        request=response.request,
                        response=response,
                    )
                    await asyncio.sleep(0.8)
                    continue
                response.raise_for_status()
                payload = response.json()
                translated = self._google_text(payload)
                if not translated:
                    last_error = ValueError("Google no devolvió traducción")
                    continue
                return (
                    html.unescape(translated)
                    .replace("\r\n", "\n")
                    .replace("\r", "\n")
                    .split("\n")
                )
        raise last_error or ValueError("Respuesta de Google inválida")

    @staticmethod
    def _google_text(payload: object) -> str:
        if not isinstance(payload, list) or not payload or not isinstance(payload[0], list):
            return ""
        first = payload[0]
        if first and isinstance(first[0], str):
            return first[0]
        return "".join(
            str(segment[0])
            for segment in first
            if isinstance(segment, list) and segment and segment[0] is not None
        )

    async def _translate_individually(
        self, texts: list[str], target_language: str
    ) -> BatchTranslation:
        translated: list[str] = []
        providers: list[str] = []
        for text in texts:
            try:
                result = await self._translate_batch([text], target_language)
                translated.append(result.texts[0] if result.texts else "")
                if result.provider not in providers:
                    providers.append(result.provider)
            except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError):
                translated.append("")
        return BatchTranslation(translated, " + ".join(providers) or "Sin proveedor")

    def _cache_path(self, query: TrackQuery, target_language: str) -> Path:
        return self.cache_dir / f"{query.key}-{target_language}.json"

    def _read_cache(
        self, query: TrackQuery, source_texts: list[str], target_language: str
    ) -> TranslationResult | None:
        try:
            payload = json.loads(
                self._cache_path(query, target_language).read_text(encoding="utf-8")
            )
            if int(payload.get("version") or 0) != self.CACHE_VERSION:
                return None
            if payload.get("source_texts") != source_texts:
                return None
            texts = payload.get("translations")
            if not isinstance(texts, list) or len(texts) != len(source_texts):
                return None
            if any(texts) or time.time() < float(payload.get("retry_after") or 0):
                return TranslationResult(
                    [str(value or "") for value in texts],
                    provider=str(payload.get("provider") or "MyMemory") if any(texts) else None,
                    cached=True,
                )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None
        return None

    def _write_cache(
        self,
        query: TrackQuery,
        source_texts: list[str],
        target_language: str,
        result: TranslationResult,
    ) -> None:
        path = self._cache_path(query, target_language)
        temporary = path.with_suffix(".tmp")
        payload = {
            "version": self.CACHE_VERSION,
            "key": query.key,
            "target_language": target_language,
            "source_texts": source_texts,
            "translations": result.texts,
            "provider": result.provider,
            "created_at": time.time(),
            "retry_after": time.time() + self.RETRY_EMPTY_SECONDS if not any(result.texts) else None,
        }
        try:
            temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            temporary.replace(path)
        except OSError:
            logger.exception("No se pudo guardar la caché de traducción %s", path)
