"""Bounded HTTP JSON reads, safe errors and a six-hour local snapshot cache."""

import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import AwareDatetime, BaseModel, JsonValue, ValidationError

from .models import RetrievalFailure


class Page(BaseModel):
    payload: dict[str, JsonValue]
    fetched_at: AwareDatetime
    cached: bool = False


class JsonClient(Protocol):
    def get(self, url: str) -> Page: ...


class HttpJsonClient:
    """Sequential client. Inject JsonClient for offline tests.

    Cache stores public responses only; never falls back to stale data on error.
    Reuse a service across a batch. Multi-process use needs a shared rate limiter.
    """

    def __init__(
        self,
        *,
        timeout: float = 15,
        retries: int = 1,
        cache_dir: Path | None = None,
        cache_seconds: float = 21600,
        sleep: Callable[[float], None] = time.sleep,
        authorization: str | None = None,
    ) -> None:
        if timeout <= 0 or not 0 <= retries <= 2 or cache_seconds < 0:
            raise ValueError("Invalid HTTP bounds")
        self.timeout = timeout
        self.retries = retries
        self.cache_dir = cache_dir
        self.cache_seconds = cache_seconds
        self.sleep = sleep
        self._authorization = authorization
        self._memory: dict[str, Page] = {}
        self._last_remotive: float | None = None

    def get(self, url: str) -> Page:
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
        for attempt in range(self.retries + 1):
            if url.startswith("https://remotive.com/"):
                if self._last_remotive is not None:
                    self.sleep(max(0, 31 - (time.monotonic() - self._last_remotive)))
                self._last_remotive = time.monotonic()
            try:
                request = Request(
                    url,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "JobScout-course-prototype/0.1",
                    },
                )
                if self._authorization:
                    # Never forward credentials if the upstream redirects to another host.
                    request.add_unredirected_header("Authorization", self._authorization)
                with urlopen(request, timeout=self.timeout) as response:
                    body = response.read(8_000_001)
                if len(body) > 8_000_000:
                    raise RetrievalFailure("SEARCH_RESPONSE_FORMAT", "Response exceeds 8 MB bound.")
                try:
                    page = Page(payload=json.loads(body), fetched_at=datetime.now(UTC))
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
                        pass  # Optional persistence; retrieval itself succeeded.
                return page
            except HTTPError as exc:
                status = exc.code
                exc.close()
                if status in {401, 403}:
                    raise RetrievalFailure(
                        "SEARCH_AUTH", "Source rejected access (401/403)."
                    ) from exc
                if status == 429:
                    raise RetrievalFailure(
                        "SEARCH_RATE_LIMIT", "Source rate limit (429); retry later."
                    ) from exc
                if status < 500:
                    raise RetrievalFailure("SEARCH_HTTP", f"Source HTTP status {status}.") from exc
                failure = RetrievalFailure("SEARCH_HTTP", f"Source HTTP status {status}.")
            except TimeoutError:
                failure = RetrievalFailure("SEARCH_TIMEOUT", "Source request timed out.")
            except URLError as exc:
                code = (
                    "SEARCH_TIMEOUT" if isinstance(exc.reason, TimeoutError) else "SEARCH_NETWORK"
                )
                failure = RetrievalFailure(code, "Source network request failed.")
            except OSError:
                failure = RetrievalFailure("SEARCH_NETWORK", "Source connection or read failed.")
            if attempt < self.retries:
                self.sleep(1.0 * (attempt + 1))
        raise failure


class FixtureClient:
    """Synthetic data goes through the same adapters and filters as live."""

    def __init__(self, fixtures: dict[str, dict[str, JsonValue]]) -> None:
        self.fixtures = fixtures

    def get(self, url: str) -> Page:
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
