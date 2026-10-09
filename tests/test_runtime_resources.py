"""Cross-client outbound limits and byte-accounted public caching."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from jobscout.config import get_settings
from jobscout.services.job_retrieval.async_transport import AsyncHttpWebClient
from jobscout.services.job_retrieval.transport import HttpJsonClient
from jobscout.services.llm_service import LangChainModelProvider
from jobscout.services.runtime_resources import (
    CachedResponse,
    PublicResponseCache,
    runtime_resources,
)
from tests.test_llm_service import Answer, messages, reply


def test_cache_byte_budget_expiry_oversized_entries_and_lru() -> None:
    now = datetime.now(UTC)
    cache = PublicResponseCache(600)
    value = CachedResponse(b"x" * 150, now, now + timedelta(seconds=10))
    cache.put("first", value, now)
    cache.put("second", value, now)
    assert cache.get("first", now) is value
    cache.put("third", value, now)
    assert cache.get("second", now) is None
    assert cache.size_bytes <= 600
    cache.put("oversized", CachedResponse(b"x" * 601, now, value.expires_at), now)
    assert cache.get("oversized", now) is None
    assert cache.get("third", value.expires_at) is None
    assert cache.get("first", value.expires_at) is None
    assert cache.size_bytes == 0


def test_public_cache_and_retrieval_slots_are_shared_across_both_client_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "retrieval_concurrency", 4)

    async def scenario() -> None:
        release = asyncio.Event()
        started = 0
        active = 0
        peak = 0
        created = 0
        original_client = httpx.AsyncClient

        def create_client(**kwargs: Any) -> httpx.AsyncClient:
            nonlocal created
            created += 1
            return original_client(**kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", create_client)

        async def respond(request: httpx.Request) -> httpx.Response:
            nonlocal started, active, peak
            started += 1
            active += 1
            peak = max(peak, active)
            try:
                await release.wait()
                return httpx.Response(200, json={"path": request.url.path})
            finally:
                active -= 1

        transport = httpx.MockTransport(respond)
        tasks: list[asyncio.Task[Any]] = []
        for index in range(12):
            if index % 2:
                tasks.append(
                    asyncio.create_task(
                        HttpJsonClient(transport=transport).get(f"https://example.invalid/{index}")
                    )
                )
            else:
                tasks.append(
                    asyncio.create_task(
                        AsyncHttpWebClient(transport=transport, interval=0).request_async(
                            f"https://example.invalid/{index}"
                        )
                    )
                )
        try:
            async with asyncio.timeout(2):
                while started < 4:
                    await asyncio.sleep(0)
            assert started == peak == 4
            assert created == 4
            release.set()
            await asyncio.gather(*tasks)
            assert started == 12 and peak == 4
            cached = await HttpJsonClient(transport=transport).get("https://example.invalid/1")
            assert cached.cached and started == 12
            private = await HttpJsonClient(transport=transport, authorization="synthetic").get(
                "https://example.invalid/1"
            )
            assert not private.cached and started == 13
            assert runtime_resources().public_cache.size_bytes <= get_settings().public_cache_bytes
        finally:
            release.set()
            await asyncio.gather(*tasks, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize("concurrency", [6, 96])
def test_model_slots_apply_across_provider_instances_and_release_on_cancellation(
    concurrency: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "model_call_concurrency", concurrency)

    async def scenario() -> None:
        release = asyncio.Event()
        active = 0
        peak = 0
        started = 0
        created = 0
        original_create = LangChainModelProvider._create_model

        def create_model(provider: LangChainModelProvider, client: httpx.AsyncClient) -> Any:
            nonlocal created
            created += 1
            return original_create(provider, client)

        monkeypatch.setattr(LangChainModelProvider, "_create_model", create_model)

        async def respond(request: httpx.Request) -> httpx.Response:
            nonlocal active, peak, started
            active += 1
            started += 1
            peak = max(active, peak)
            try:
                await release.wait()
                return reply()
            finally:
                active -= 1

        settings = get_settings().model_copy(update={"llm_semantic_api_key": "synthetic"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            providers = [
                LangChainModelProvider(settings, client=client) for _ in range(concurrency * 2)
            ]
            tasks = [
                asyncio.create_task(provider.structured(Answer, messages()))
                for provider in providers
            ]
            try:
                async with asyncio.timeout(3):
                    while started < concurrency:
                        await asyncio.sleep(0)
                assert started == peak == concurrency
                assert created == concurrency
                tasks[0].cancel()
                async with asyncio.timeout(3):
                    while started < concurrency + 1:
                        await asyncio.sleep(0)
                assert peak == concurrency
                assert created == concurrency + 1
                release.set()
                results = await asyncio.gather(*tasks, return_exceptions=True)
                assert isinstance(results[0], asyncio.CancelledError)
                assert all(isinstance(result, Answer) for result in results[1:])
                assert active == 0 and not runtime_resources().models.locked()
            finally:
                release.set()
                await asyncio.gather(*tasks, return_exceptions=True)

    asyncio.run(scenario())
