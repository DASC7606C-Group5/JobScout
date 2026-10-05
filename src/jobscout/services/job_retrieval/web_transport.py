"""Shared asynchronous web transport contract and response data."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class WebPage:
    text: str
    fetched_at: datetime
    cached: bool = False


class AsyncWebClient(Protocol):
    async def request_async(
        self,
        url: str,
        *,
        body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> WebPage: ...
