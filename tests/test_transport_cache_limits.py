"""Request pacing and cache lifetime regressions using offline HTTP responses."""

import asyncio
import hashlib
import warnings
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Self

import httpx
import pytest

from jobscout.services.job_retrieval import async_transport, transport
from jobscout.services.job_retrieval.async_transport import AsyncHttpWebClient
from jobscout.services.job_retrieval.models import RetrievalFailure
from jobscout.services.job_retrieval.transport import HttpJsonClient, Page
from jobscout.services.job_retrieval.web_transport import WebPage

type Client = AsyncHttpWebClient | HttpJsonClient


class Clock(datetime):
    current = datetime(2026, 10, 8, tzinfo=UTC)

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> Self:
        return cls.fromtimestamp(cls.current.timestamp(), tz)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> type[Clock]:
    Clock.current = datetime(2026, 10, 8, tzinfo=UTC)
    monkeypatch.setattr(async_transport, "datetime", Clock)
    monkeypatch.setattr(transport, "datetime", Clock)
    return Clock


def make_client(kind: str, mock: httpx.MockTransport, *, cache_seconds: float = 5) -> Client:
    if kind == "web":
        return AsyncHttpWebClient(
            transport=mock, interval=0, retries=0, cache_seconds=cache_seconds
        )
    return HttpJsonClient(transport=mock, retries=0, cache_seconds=cache_seconds)


async def fetch(client: Client, url: str) -> Page | WebPage:
    if isinstance(client, AsyncHttpWebClient):
        return await client.request_async(url)
    return await client.get(url)


@pytest.mark.parametrize("kind", ["web", "json"])
def test_memory_cache_expires_from_original_fetch(kind: str, clock: type[Clock]) -> None:
    requested_urls: list[str] = []
    url = "https://example.invalid/jobs"

    async def respond(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200, json={"jobs": []})

    async def scenario() -> None:
        client = make_client(kind, httpx.MockTransport(respond))
        first = await fetch(client, url)
        clock.current += timedelta(seconds=4)
        cached = await fetch(client, url)
        assert cached.cached and cached.fetched_at == first.fetched_at
        clock.current += timedelta(seconds=2)
        refreshed = await fetch(client, url)
        assert not refreshed.cached and refreshed.fetched_at == clock.current
        assert requested_urls == [url, url]

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["web", "json"])
def test_cache_capacity_keeps_recently_used_response(kind: str) -> None:
    requested_ids: list[str] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        requested_ids.append(request.url.path)
        return httpx.Response(200, json={"job_id": request.url.path})

    async def scenario() -> None:
        client = make_client(kind, httpx.MockTransport(respond), cache_seconds=300)
        for index in range(128):
            await fetch(client, f"https://example.invalid/{index}")
        await fetch(client, "https://example.invalid/0")
        await fetch(client, "https://example.invalid/128")
        retained = await fetch(client, "https://example.invalid/0")
        replaced = await fetch(client, "https://example.invalid/1")
        assert retained.cached and not replaced.cached
        assert requested_ids == [*(f"/{index}" for index in range(129)), "/1"]

    asyncio.run(scenario())


def test_disk_restore_does_not_extend_memory_cache_expiry(
    tmp_path: Path, clock: type[Clock]
) -> None:
    requested_urls: list[str] = []
    url = "https://example.invalid/jobs"

    async def respond(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200, json={"jobs": []})

    async def scenario() -> None:
        mock = httpx.MockTransport(respond)
        first = await HttpJsonClient(cache_dir=tmp_path, transport=mock, cache_seconds=5).get(url)
        clock.current += timedelta(seconds=4)
        restored_client = HttpJsonClient(cache_dir=tmp_path, transport=mock, cache_seconds=5)
        restored = await restored_client.get(url)
        assert restored.cached and restored.fetched_at == first.fetched_at
        clock.current += timedelta(seconds=2)
        refreshed = await restored_client.get(url)
        assert not refreshed.cached and refreshed.fetched_at == clock.current
        assert requested_urls == [url, url]

    asyncio.run(scenario())


def test_corrupt_disk_cache_is_replaced_by_a_fresh_response(tmp_path: Path) -> None:
    url = "https://example.invalid/jobs"
    path = tmp_path / f"{hashlib.sha256(url.encode()).hexdigest()}.json"
    path.write_bytes(b"\xff\xfe")
    requested_urls: list[str] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200, json={"job_id": "fresh"})

    result = asyncio.run(
        HttpJsonClient(cache_dir=tmp_path, transport=httpx.MockTransport(respond)).get(url)
    )
    assert result.payload == {"job_id": "fresh"}
    assert not result.cached
    assert Page.model_validate_json(path.read_text(encoding="utf-8")).payload == result.payload
    assert requested_urls == [url]


@pytest.mark.parametrize("kind", ["web", "json"])
def test_expired_memory_response_does_not_hide_source_failure(
    kind: str, clock: type[Clock]
) -> None:
    requested_urls: list[str] = []
    url = "https://example.invalid/jobs"

    async def respond(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200 if len(requested_urls) == 1 else 503, json={"jobs": []})

    async def scenario() -> None:
        client = make_client(kind, httpx.MockTransport(respond))
        await fetch(client, url)
        clock.current += timedelta(seconds=6)
        with pytest.raises(RetrievalFailure) as error:
            await fetch(client, url)
        assert error.value.code == "SEARCH_HTTP"
        assert requested_urls == [url, url]

    asyncio.run(scenario())


def test_private_responses_are_not_shared_or_cached() -> None:
    requested_tokens: list[str] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        token = request.headers["authorization"]
        requested_tokens.append(token)
        return httpx.Response(200, text=token)

    async def scenario() -> None:
        client = AsyncHttpWebClient(transport=httpx.MockTransport(respond), interval=0)
        url = "https://example.invalid/jobs"
        first = await client.request_async(url, headers={"Authorization": "Bearer first"})
        second = await client.request_async(url, headers={"Authorization": "Bearer second"})
        cached = await client.request_async(url, headers={"authorization": "Bearer first"})
        assert first.text == cached.text == "Bearer first" and not cached.cached
        assert second.text == "Bearer second" and not second.cached
        assert requested_tokens == ["Bearer first", "Bearer second", "Bearer first"]

    asyncio.run(scenario())


def test_request_pacing_is_independent_for_each_host() -> None:
    async def scenario() -> None:
        starts: list[tuple[str, float]] = []

        async def respond(request: httpx.Request) -> httpx.Response:
            starts.append((request.url.host, asyncio.get_running_loop().time()))
            return httpx.Response(200, json={})

        client = AsyncHttpWebClient(transport=httpx.MockTransport(respond), interval=0.05)
        await client.request_async("https://first.invalid/1")
        await asyncio.gather(
            client.request_async("https://first.invalid/2"),
            client.request_async("https://second.invalid/1"),
        )
        assert [host for host, _ in starts] == ["first.invalid", "second.invalid", "first.invalid"]
        assert starts[2][1] - starts[0][1] >= 0.04

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["web", "jobsdb", "json"])
def test_cancelling_pacing_wait_prevents_request(kind: str) -> None:
    requested_urls: list[str] = []
    limited_host = {
        "web": "https://example.invalid",
        "jobsdb": "https://hk.jobsdb.com",
        "json": "https://remotive.com",
    }[kind]

    async def respond(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200, json={})

    async def scenario() -> None:
        mock = httpx.MockTransport(respond)
        client: Client = (
            HttpJsonClient(transport=mock)
            if kind == "json"
            else AsyncHttpWebClient(transport=mock, interval=31)
        )
        await fetch(client, f"{limited_host}/first")
        blocked = asyncio.create_task(fetch(client, f"{limited_host}/cancelled"))
        try:
            await asyncio.sleep(0)
            blocked.cancel()
            with pytest.raises(asyncio.CancelledError):
                await blocked
            async with asyncio.timeout(1):
                await fetch(client, "https://other.invalid/free")
            assert requested_urls == [f"{limited_host}/first", "https://other.invalid/free"]
        finally:
            blocked.cancel()
            await asyncio.gather(blocked, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["web", "json"])
def test_limiters_are_not_reused_across_event_loops(kind: str) -> None:
    requested_urls: list[str] = []
    host = "https://remotive.com" if kind == "json" else "https://hk.jobsdb.com"

    async def respond(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200, json={})

    mock = httpx.MockTransport(respond)
    client: Client = (
        HttpJsonClient(transport=mock)
        if kind == "json"
        else AsyncHttpWebClient(transport=mock, interval=0.05)
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        asyncio.run(fetch(client, f"{host}/first"))
        asyncio.run(fetch(client, f"{host}/second"))
    assert requested_urls == [f"{host}/first", f"{host}/second"]


@pytest.mark.parametrize(("first_interval", "second_interval"), [(0.01, 0.05), (0.05, 0.01)])
def test_jobsdb_clients_with_different_intervals_keep_the_stricter_limit(
    first_interval: float, second_interval: float
) -> None:
    async def scenario() -> None:
        starts: list[float] = []

        async def respond(request: httpx.Request) -> httpx.Response:
            starts.append(asyncio.get_running_loop().time())
            return httpx.Response(200, json={})

        mock = httpx.MockTransport(respond)
        first = AsyncHttpWebClient(transport=mock, interval=first_interval)
        second = AsyncHttpWebClient(transport=mock, interval=second_interval)
        await first.request_async("https://hk.jobsdb.com/first")
        await second.request_async("https://hk.jobsdb.com/second")
        await first.request_async("https://hk.jobsdb.com/third")
        assert starts[1] - starts[0] >= 0.045
        assert starts[2] - starts[1] >= 0.045

    asyncio.run(scenario())


def test_concurrent_json_reads_share_fetch_and_keep_independent_payloads() -> None:
    async def scenario() -> None:
        started, release = asyncio.Event(), asyncio.Event()
        urls: list[str] = []
        url = "https://example.invalid/jobs"

        async def respond(request: httpx.Request) -> httpx.Response:
            urls.append(str(request.url))
            started.set()
            await release.wait()
            return httpx.Response(200, json={"job_id": "original"})

        client = HttpJsonClient(transport=httpx.MockTransport(respond), cache_seconds=0)
        first = asyncio.create_task(client.get(url))
        await started.wait()
        second = asyncio.create_task(client.get(url))
        await asyncio.sleep(0)
        release.set()
        one, two = await asyncio.gather(first, second)
        assert urls == [url]
        one.payload["job_id"] = "changed"
        assert two.payload["job_id"] == "original"
        assert (await client.get(url)).payload["job_id"] == "original"
        assert urls == [url, url]

    asyncio.run(scenario())


def test_cancelling_one_json_waiter_keeps_the_other_request() -> None:
    async def scenario() -> None:
        started, release = asyncio.Event(), asyncio.Event()
        urls: list[str] = []
        url = "https://example.invalid/jobs"

        async def respond(request: httpx.Request) -> httpx.Response:
            urls.append(str(request.url))
            started.set()
            await release.wait()
            return httpx.Response(200, json={"job_id": "kept"})

        client = HttpJsonClient(transport=httpx.MockTransport(respond))
        first = asyncio.create_task(client.get(url))
        await started.wait()
        second = asyncio.create_task(client.get(url))
        await asyncio.sleep(0)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        release.set()
        assert (await second).payload["job_id"] == "kept"
        assert urls == [url]

    asyncio.run(scenario())


def test_cancelling_all_json_waiters_closes_fetch_and_allows_retry() -> None:
    async def scenario() -> None:
        started, cancelled = asyncio.Event(), asyncio.Event()
        urls: list[str] = []
        url = "https://example.invalid/jobs"

        async def respond(request: httpx.Request) -> httpx.Response:
            urls.append(str(request.url))
            if len(urls) == 1:
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            return httpx.Response(200, json={"job_id": "retried"})

        client = HttpJsonClient(transport=httpx.MockTransport(respond))
        first = asyncio.create_task(client.get(url))
        await started.wait()
        second = asyncio.create_task(client.get(url))
        await asyncio.sleep(0)
        first.cancel()
        second.cancel()
        for task in (first, second):
            with pytest.raises(asyncio.CancelledError):
                await task
        async with asyncio.timeout(1):
            await cancelled.wait()
            assert (await client.get(url)).payload["job_id"] == "retried"
        assert urls == [url, url]

    asyncio.run(scenario())
