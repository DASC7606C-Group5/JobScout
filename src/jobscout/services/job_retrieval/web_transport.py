"""Bounded, injectable HTTP transport for public search JSON and HTML."""

import gzip
import io
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from http.client import HTTPException
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .models import RetrievalFailure


@dataclass(frozen=True)
class WebPage:
    text: str
    fetched_at: datetime
    cached: bool = False


class WebClient(Protocol):
    def request(
        self,
        url: str,
        *,
        body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> WebPage: ...


class HttpWebClient:
    """Public reads only; no account cookies. Cache retains actual fetch timestamps."""

    def __init__(
        self,
        *,
        timeout: float = 12,
        retries: int = 1,
        cache_seconds: float = 300,
        interval: float = 0.3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if timeout <= 0 or not 0 <= retries <= 2 or cache_seconds < 0 or interval < 0:
            raise ValueError("Invalid HTTP bounds")
        self.timeout, self.retries, self.cache_seconds = timeout, retries, cache_seconds
        self.interval, self.sleep = interval, sleep
        self._cache: dict[str, WebPage] = {}
        self._last: dict[str, float] = {}

    def request(
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
        for attempt in range(self.retries + 1):
            self.sleep(max(0, self.interval - (time.monotonic() - self._last.get(host, 0))))
            self._last[host] = time.monotonic()
            try:
                request = Request(
                    url,
                    data=json.dumps(body).encode() if body is not None else None,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
                        "Accept": "application/json,text/html",
                        "Content-Type": "application/json",
                        **(headers or {}),
                    },
                )
                with urlopen(request, timeout=self.timeout) as response:
                    raw = response.read(4_000_001)
                    if response.headers.get("Content-Encoding") == "gzip":
                        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
                            raw = compressed.read(4_000_001)
                    charset = response.headers.get_content_charset() or "utf-8"
                if len(raw) > 4_000_000:
                    raise RetrievalFailure("SEARCH_RESPONSE_FORMAT", "Response exceeds 4 MB bound.")
                page = WebPage(raw.decode(charset), datetime.now(UTC))
                if len(self._cache) >= 128:
                    self._cache.pop(next(iter(self._cache)))
                self._cache[key] = page
                return page
            except HTTPError as exc:
                status = exc.code
                exc.close()
                if status in {401, 403, 429}:
                    code = "SEARCH_RATE_LIMIT" if status == 429 else "SEARCH_AUTH"
                    raise RetrievalFailure(
                        code, f"Source rejected request (HTTP {status})."
                    ) from exc
                failure = RetrievalFailure("SEARCH_HTTP", f"Source HTTP {status}.")
                if status < 500:
                    raise failure from exc
            except TimeoutError:
                failure = RetrievalFailure("SEARCH_TIMEOUT", "Source request timed out.")
            except URLError as exc:
                code = (
                    "SEARCH_TIMEOUT" if isinstance(exc.reason, TimeoutError) else "SEARCH_NETWORK"
                )
                failure = RetrievalFailure(code, "Source network request failed.")
            except (UnicodeError, ValueError, EOFError, LookupError) as exc:
                raise RetrievalFailure(
                    "SEARCH_RESPONSE_FORMAT", "Cannot decode source response."
                ) from exc
            except OSError, HTTPException:
                failure = RetrievalFailure("SEARCH_NETWORK", "Source connection/read failed.")
            if attempt < self.retries:
                self.sleep(attempt + 1)
        raise failure
