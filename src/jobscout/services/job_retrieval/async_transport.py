"""Native asynchronous public HTTP reads; cancellation covers I/O and retry waits."""

import asyncio
import json
import time
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from .models import RetrievalFailure
from .web_transport import WebPage


class AsyncHttpWebClient:
    def __init__(
        self,
        *,
        timeout: float = 12.0,
        retries: int = 1,
        interval: float = 0.3,
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
        self._cache: dict[str, WebPage] = {}
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def request_async(
        self,
        url: str,
        *,
        body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> WebPage:
        key = url + json.dumps(body, sort_keys=True)
        cached = self._cache.get(key)
        if (
            cached
            and 0 <= (datetime.now(UTC) - cached.fetched_at).total_seconds() < self.cache_seconds
        ):
            return WebPage(cached.text, cached.fetched_at, True)
        host = urlsplit(url).netloc
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with httpx.AsyncClient(
            timeout=self.timeout, transport=self.transport, follow_redirects=True
        ) as client:
            for attempt in range(self.retries + 1):
                async with lock:
                    await asyncio.sleep(
                        max(0, self.interval - (time.monotonic() - self._last.get(host, 0)))
                    )
                    self._last[host] = time.monotonic()
                try:
                    async with client.stream(
                        "POST" if body is not None else "GET",
                        url,
                        json=body,
                        headers={
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
                            "Accept": "application/json,text/html",
                            **(headers or {}),
                        },
                    ) as response:
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
                    if len(self._cache) >= 128:
                        self._cache.pop(next(iter(self._cache)))
                    self._cache[key] = page
                    return page
                except httpx.TimeoutException:
                    failure = RetrievalFailure("SEARCH_TIMEOUT", "Source request timed out.")
                except httpx.HTTPStatusError as exc:
                    failure = RetrievalFailure(
                        "SEARCH_HTTP", f"Source HTTP {exc.response.status_code}."
                    )
                    if exc.response.status_code < 500:
                        raise failure from exc
                except httpx.RequestError:
                    failure = RetrievalFailure("SEARCH_NETWORK", "Source connection/read failed.")
                except (UnicodeError, LookupError) as exc:
                    raise RetrievalFailure(
                        "SEARCH_RESPONSE_FORMAT", "Cannot decode source response."
                    ) from exc
                if attempt < self.retries:
                    await asyncio.sleep(attempt + 1)
        raise failure
