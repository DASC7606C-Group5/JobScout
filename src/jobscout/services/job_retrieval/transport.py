"""Bounded HTTP JSON reads, safe errors and a six-hour local snapshot cache."""

import asyncio
import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import httpx
from pydantic import AwareDatetime, BaseModel, JsonValue, ValidationError

from .models import RetrievalFailure


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
        self._remotive_lock = asyncio.Lock()
        self._memory: dict[str, Page] = {}
        self._last_remotive: float | None = None

    async def get(self, url: str) -> Page:
        key = hashlib.sha256(url.encode()).hexdigest()
        path = self.cache_dir / f"{key}.json" if self.cache_dir else None
        page = self._memory.get(key)
        if page is None and path and path.exists():
            try:
                page = Page.model_validate_json(path.read_text(encoding="utf-8"))
            except OSError, ValidationError:
                page = None
        if page and 0 <= (datetime.now(UTC) - page.fetched_at).total_seconds() < self.cache_seconds:
            return page.model_copy(update={"cached": True})
        headers = {
            "Accept": "application/json",
            "User-Agent": "JobScout-course-prototype/0.1",
        }
        if self._authorization:
            headers["Authorization"] = self._authorization
        async with httpx.AsyncClient(
            timeout=self.timeout, transport=self.transport, follow_redirects=True
        ) as client:
            for attempt in range(self.retries + 1):
                if url.startswith("https://remotive.com/"):
                    async with self._remotive_lock:
                        if self._last_remotive is not None:
                            await self.sleep(max(0, 31 - (time.monotonic() - self._last_remotive)))
                        self._last_remotive = time.monotonic()
                try:
                    # httpx strips Authorization when a redirect changes origin.
                    async with client.stream("GET", url, headers=headers) as response:
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
                    self._memory[key] = page
                    if path:
                        try:
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_text(page.model_dump_json(), encoding="utf-8")
                        except OSError:
                            pass
                    return page
                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code
                    failure = RetrievalFailure("SEARCH_HTTP", f"Source HTTP status {status}.")
                    if status < 500:
                        raise failure from exc
                except httpx.TimeoutException, TimeoutError:
                    failure = RetrievalFailure("SEARCH_TIMEOUT", "Source request timed out.")
                except httpx.RequestError, OSError:
                    failure = RetrievalFailure(
                        "SEARCH_NETWORK", "Source connection or read failed."
                    )
                if attempt < self.retries:
                    await self.sleep(float(attempt + 1))
        raise failure


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
