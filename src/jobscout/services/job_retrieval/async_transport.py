"""Fetch public HTTP data asynchronously; cancellation stops requests and retry waits."""

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx
from aiolimiter import AsyncLimiter
from tenacity import AsyncRetrying, stop_after_attempt, wait_incrementing

from jobscout.services.runtime_resources import CachedResponse, runtime_resources

from .models import RetrievalFailure
from .retries import source_retry
from .web_transport import WebPage


@dataclass
class _JobsdbLimit:
    limiter: AsyncLimiter
    lock: asyncio.Lock


_JOBSDB_LIMITERS: dict[asyncio.AbstractEventLoop, _JobsdbLimit] = {}


async def _pace_jobsdb_requests(interval: float) -> None:
    loop = asyncio.get_running_loop()
    for closed_loop in tuple(_JOBSDB_LIMITERS):
        if closed_loop.is_closed():
            del _JOBSDB_LIMITERS[closed_loop]
    limit = _JOBSDB_LIMITERS.setdefault(
        loop, _JobsdbLimit(AsyncLimiter(1, interval), asyncio.Lock())
    )
    async with limit.lock:
        if interval > limit.limiter.time_period:
            limit.limiter = AsyncLimiter(1, interval)
            # The stricter interval also applies after requests already started.
            await limit.limiter.acquire()
        await limit.limiter.acquire()


class AsyncHttpWebClient:
    def __init__(
        self,
        *,
        timeout: float = 12.0,
        retries: int = 1,
        interval: float = 0.6,
        cache_seconds: float = 300,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if timeout <= 0 or not 0 <= retries <= 2 or interval < 0 or cache_seconds < 0:
            raise ValueError("Invalid HTTP bounds")
        self.timeout = timeout
        self.retries = retries
        self.interval = interval
        self.cache_seconds = cache_seconds
        self.transport = transport
        self._limiters: dict[asyncio.AbstractEventLoop, dict[str, AsyncLimiter]] = {}

    async def _pace_requests(self, host: str) -> None:
        if self.interval == 0:
            return
        if host == "hk.jobsdb.com":
            await _pace_jobsdb_requests(self.interval)
            return
        loop = asyncio.get_running_loop()
        for closed_loop in tuple(self._limiters):
            if closed_loop.is_closed():
                del self._limiters[closed_loop]
        limiters = self._limiters.setdefault(loop, {})
        await limiters.setdefault(host, AsyncLimiter(1, self.interval)).acquire()

    async def request_async(
        self,
        url: str,
        *,
        body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> WebPage:
        key = json.dumps([url, body, dict(httpx.Headers(headers))], sort_keys=True)
        public = not any(
            name.lower() in {"authorization", "cookie", "x-api-key", "api-key"}
            for name in (headers or {})
        )
        cache = runtime_resources().public_cache
        cache_key = (
            f"web:{id(self.transport) if self.transport else 'live'}:{self.cache_seconds}:{key}"
        )
        cached = cache.get(cache_key, datetime.now(UTC)) if public else None
        if cached is not None and cached.fetched_at <= datetime.now(UTC):
            return WebPage(cached.body.decode(cached.encoding), cached.fetched_at, True)
        host = urlsplit(url).netloc
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self.retries + 1),
                wait=wait_incrementing(start=1, increment=1),
                retry=source_retry,
                sleep=asyncio.sleep,
                reraise=True,
            ):
                with attempt:
                    await self._pace_requests(host)
                    async with (
                        runtime_resources().retrieval,
                        httpx.AsyncClient(
                            timeout=self.timeout, transport=self.transport, follow_redirects=False
                        ) as client,
                        client.stream(
                            "POST" if body is not None else "GET",
                            url,
                            json=body,
                            headers={
                                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
                                "Accept": "application/json,text/html",
                                **(headers or {}),
                            },
                        ) as response,
                    ):
                        if response.headers.get("cf-mitigated") == "challenge":
                            raise RetrievalFailure(
                                "SEARCH_AUTH", "Source requires Cloudflare verification."
                            )
                        if response.status_code in {401, 403, 429}:
                            raise RetrievalFailure(
                                "SEARCH_RATE_LIMIT"
                                if response.status_code == 429
                                else "SEARCH_AUTH",
                                "Source blocked access or requires verification.",
                            )
                        response.raise_for_status()
                        chunks: list[bytes] = []
                        size = 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > 4_000_000:
                                raise RetrievalFailure(
                                    "SEARCH_RESPONSE_FORMAT", "Response exceeds 4 MB bound."
                                )
                            chunks.append(chunk)
                        page = WebPage(
                            b"".join(chunks).decode(response.charset_encoding or "utf-8"),
                            datetime.now(UTC),
                        )
                    if public:
                        cache.put(
                            cache_key,
                            CachedResponse(
                                b"".join(chunks),
                                page.fetched_at,
                                page.fetched_at + timedelta(seconds=self.cache_seconds),
                                response.charset_encoding or "utf-8",
                            ),
                            datetime.now(UTC),
                        )
                    return page
        except httpx.TimeoutException:
            raise RetrievalFailure("SEARCH_TIMEOUT", "Source request timed out.") from None
        except httpx.HTTPStatusError as exc:
            raise RetrievalFailure(
                "SEARCH_HTTP", f"Source HTTP {exc.response.status_code}."
            ) from exc
        except httpx.RequestError:
            raise RetrievalFailure("SEARCH_NETWORK", "Source connection/read failed.") from None
        except (UnicodeError, LookupError) as exc:
            raise RetrievalFailure(
                "SEARCH_RESPONSE_FORMAT", "Cannot decode source response."
            ) from exc
        raise RuntimeError("HTTP retry loop ended without a result")
