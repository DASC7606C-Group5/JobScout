"""One byte-bounded public response cache and outbound limits per application loop."""

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime

from jobscout.config import get_settings


@dataclass(frozen=True)
class CachedResponse:
    body: bytes
    fetched_at: datetime
    expires_at: datetime
    encoding: str = "utf-8"


class PublicResponseCache:
    def __init__(self, max_bytes: int, max_entries: int = 128) -> None:
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        self.size_bytes = 0
        self.entries: OrderedDict[str, CachedResponse] = OrderedDict()

    @staticmethod
    def weight(key: str, value: CachedResponse) -> int:
        return len(key.encode()) + len(value.body) + 128

    def discard(self, key: str) -> None:
        value = self.entries.pop(key, None)
        if value is not None:
            self.size_bytes -= self.weight(key, value)

    def get(self, key: str, now: datetime) -> CachedResponse | None:
        value = self.entries.get(key)
        if value is None:
            return None
        if not value.fetched_at <= now < value.expires_at:
            self.discard(key)
            return None
        self.entries.move_to_end(key)
        return value

    def put(self, key: str, value: CachedResponse, now: datetime) -> None:
        self.discard(key)
        for expired in tuple(self.entries):
            if self.entries[expired].expires_at <= now:
                self.discard(expired)
        weight = self.weight(key, value)
        if weight > self.max_bytes or not value.fetched_at <= now < value.expires_at:
            return
        while self.entries and (
            self.size_bytes + weight > self.max_bytes or len(self.entries) >= self.max_entries
        ):
            self.discard(next(iter(self.entries)))
        self.entries[key] = value
        self.size_bytes += weight


class RuntimeResources:
    def __init__(self) -> None:
        settings = get_settings()
        self.models = asyncio.Semaphore(settings.model_call_concurrency)
        self.retrieval = asyncio.Semaphore(settings.retrieval_concurrency)
        self.public_cache = PublicResponseCache(settings.public_cache_bytes)


_RESOURCES: dict[asyncio.AbstractEventLoop, RuntimeResources] = {}


def runtime_resources() -> RuntimeResources:
    for loop in tuple(_RESOURCES):
        if loop.is_closed():
            del _RESOURCES[loop]
    loop = asyncio.get_running_loop()
    if loop not in _RESOURCES:
        _RESOURCES[loop] = RuntimeResources()
    return _RESOURCES[loop]


def release_runtime_resources() -> None:
    _RESOURCES.pop(asyncio.get_running_loop(), None)
