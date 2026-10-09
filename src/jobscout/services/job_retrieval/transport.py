"""Bounded HTTP JSON reads, safe errors and a six-hour local snapshot cache."""

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

import httpx
from aiolimiter import AsyncLimiter
from async_lru import alru_cache
from pydantic import AwareDatetime, BaseModel, JsonValue, ValidationError
from tenacity import AsyncRetrying, stop_after_attempt, wait_incrementing

from jobscout.services.runtime_resources import CachedResponse, runtime_resources

from .models import RetrievalFailure
from .retries import source_retry


class Page(BaseModel):
    payload: dict[str, JsonValue]
    fetched_at: AwareDatetime
    cached: bool = False


class JsonClient(Protocol):
    async def get(self, url: str) -> Page: ...


class HttpJsonClient:
    """Cancellable JSON requests with bounded retries and public response caching.

    Cache never falls back to stale data on error. Remotive starts are spaced
    across concurrent calls; multi-process use needs a shared rate limiter.
    """

    def __init__(
        self,
        *,
        timeout: float = 15,
        retries: int = 1,
        cache_dir: Path | None = None,
        cache_seconds: float = 21600,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        authorization: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if timeout <= 0 or not 0 <= retries <= 2 or cache_seconds < 0:
            raise ValueError("Invalid HTTP bounds")
        self.timeout = timeout
        self.retries = retries
        self.cache_dir = cache_dir if authorization is None else None
        self.cache_seconds = cache_seconds
        self.sleep = sleep
        self._authorization = authorization
        self.transport = transport
        self._reads: dict[asyncio.AbstractEventLoop, Callable[[str], Awaitable[Page]]] = {}
        self._remotive_limiters: dict[asyncio.AbstractEventLoop, AsyncLimiter] = {}

    async def _pace_remotive_requests(self) -> None:
        loop = asyncio.get_running_loop()
        for closed_loop in tuple(self._remotive_limiters):
            if closed_loop.is_closed():
                del self._remotive_limiters[closed_loop]
        await self._remotive_limiters.setdefault(loop, AsyncLimiter(1, 31)).acquire()

    async def get(self, url: str) -> Page:
        loop = asyncio.get_running_loop()
        for closed_loop in tuple(self._reads):
            if closed_loop.is_closed():
                del self._reads[closed_loop]
        if loop not in self._reads:
            read = alru_cache(maxsize=128, ttl=0)(self._get)

            async def inflight_only(url: str) -> Page:
                page = await read(url)
                read.cache_invalidate(url)
                return page

            self._reads[loop] = inflight_only
        return (await self._reads[loop](url)).model_copy(deep=True)

    async def _get(self, url: str) -> Page:
        key = hashlib.sha256(url.encode()).hexdigest()
        path = self.cache_dir / f"{key}.json" if self.cache_dir else None
        cache = runtime_resources().public_cache
        cache_key = (
            f"json:{id(self.transport) if self.transport else 'live'}:{self.cache_seconds}:{key}"
        )
        cached = cache.get(cache_key, datetime.now(UTC)) if self._authorization is None else None
        if cached:
            return Page(payload=json.loads(cached.body), fetched_at=cached.fetched_at, cached=True)
        if path and path.exists() and path.stat().st_size <= 9_000_000:
            try:
                restored = Page.model_validate_json(path.read_text(encoding="utf-8"))
                expires = restored.fetched_at + timedelta(seconds=self.cache_seconds)
                if restored.fetched_at <= datetime.now(UTC) < expires:
                    cache.put(
                        cache_key,
                        CachedResponse(
                            json.dumps(restored.payload).encode(), restored.fetched_at, expires
                        ),
                        datetime.now(UTC),
                    )
                    return restored.model_copy(update={"cached": True})
            except OSError, UnicodeError, ValidationError:
                pass
        headers = {
            "Accept": "application/json",
            "User-Agent": "JobScout-course-prototype/0.1",
        }
        if self._authorization:
            headers["Authorization"] = self._authorization
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self.retries + 1),
                wait=wait_incrementing(start=1, increment=1),
                retry=source_retry,
                sleep=self.sleep,
                reraise=True,
            ):
                with attempt:
                    if url.startswith("https://remotive.com/"):
                        await self._pace_remotive_requests()
                    async with (
                        runtime_resources().retrieval,
                        httpx.AsyncClient(
                            timeout=self.timeout, transport=self.transport, follow_redirects=False
                        ) as client,
                        client.stream("GET", url, headers=headers) as response,
                    ):
                        if response.status_code in {401, 403}:
                            raise RetrievalFailure(
                                "SEARCH_AUTH", "Source rejected access (401/403)."
                            )
                        if response.status_code == 429:
                            raise RetrievalFailure(
                                "SEARCH_RATE_LIMIT", "Source rate limit (429); retry later."
                            )
                        response.raise_for_status()
                        chunks: list[bytes] = []
                        size = 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > 8_000_000:
                                raise RetrievalFailure(
                                    "SEARCH_RESPONSE_FORMAT", "Response exceeds 8 MB bound."
                                )
                            chunks.append(chunk)
                    try:
                        page = Page(
                            payload=json.loads(b"".join(chunks)), fetched_at=datetime.now(UTC)
                        )
                    except (ValueError, UnicodeError) as exc:
                        raise RetrievalFailure(
                            "SEARCH_RESPONSE_FORMAT", "Expected a JSON object."
                        ) from exc
                    if self._authorization is None:
                        cache.put(
                            cache_key,
                            CachedResponse(
                                b"".join(chunks),
                                page.fetched_at,
                                page.fetched_at + timedelta(seconds=self.cache_seconds),
                            ),
                            datetime.now(UTC),
                        )
                    if path:
                        try:
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_text(page.model_dump_json(), encoding="utf-8")
                        except OSError:
                            pass
                    return page
        except httpx.HTTPStatusError as exc:
            raise RetrievalFailure(
                "SEARCH_HTTP", f"Source HTTP status {exc.response.status_code}."
            ) from exc
        except httpx.TimeoutException, TimeoutError:
            raise RetrievalFailure("SEARCH_TIMEOUT", "Source request timed out.") from None
        except httpx.RequestError, OSError:
            raise RetrievalFailure("SEARCH_NETWORK", "Source connection or read failed.") from None
        raise RuntimeError("HTTP retry loop ended without a result")


class FixtureClient:
    """Synthetic data goes through the same adapters and filters as live."""

    def __init__(self, fixtures: dict[str, dict[str, JsonValue]]) -> None:
        self.fixtures = fixtures

    async def get(self, url: str) -> Page:
        from urllib.parse import parse_qs, urlparse

        if url.startswith("https://search.api.careerjet.net/"):
            query = parse_qs(urlparse(url).query)
            locale = query.get("locale_code", [""])[0]
            source = "careerjet_hk" if locale == "en_HK" else "careerjet_cn"
            payload = dict(self.fixtures[source])
            records = payload.get("jobs")
            if isinstance(records, list):
                terms = query.get("keywords", [""])[0].casefold().split()
                payload["jobs"] = [
                    r
                    for r in records
                    if isinstance(r, dict)
                    and all(
                        term in f"{r.get('title', '')} {r.get('description', '')}".casefold()
                        for term in terms
                    )
                ]
            return Page(payload=payload, fetched_at=datetime(2026, 10, 1, tzinfo=UTC))
        else:
            source = "remotive" if url.startswith("https://remotive.com/") else "arbeitnow"
        return Page(payload=self.fixtures[source], fetched_at=datetime(2026, 10, 1, tzinfo=UTC))
