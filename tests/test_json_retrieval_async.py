import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest
from pydantic import JsonValue

from jobscout.schemas.search import SearchRequest
from jobscout.services.job_retrieval.careerjet import CareerjetAdapter
from jobscout.services.job_retrieval.sources import FeedAdapter, SourceAdapter, SourceResult
from jobscout.services.job_retrieval.transport import FixtureClient, HttpJsonClient
from jobscout.services.job_search_service import JobSearchService


def test_json_cancellation_closes_response_stream() -> None:
    async def scenario() -> None:
        reading = asyncio.Event()
        closed = asyncio.Event()

        class PendingStream(httpx.AsyncByteStream):
            async def __aiter__(self) -> AsyncIterator[bytes]:
                reading.set()
                await asyncio.Event().wait()
                yield b"{}"

            async def aclose(self) -> None:
                closed.set()

        async def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, stream=PendingStream())

        client = HttpJsonClient(transport=httpx.MockTransport(respond))
        operation = asyncio.create_task(client.get("https://example.invalid/jobs"))
        try:
            async with asyncio.timeout(2):
                await reading.wait()
                operation.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await operation
            assert closed.is_set()
        finally:
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)

    asyncio.run(scenario())


def test_search_deadline_cancels_json_retry_wait() -> None:
    async def scenario() -> None:
        retry_started = asyncio.Event()
        retry_cancelled = asyncio.Event()
        requested_urls: list[str] = []

        async def respond(request: httpx.Request) -> httpx.Response:
            requested_urls.append(str(request.url))
            return httpx.Response(503)

        async def wait_before_retry(delay: float) -> None:
            retry_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                retry_cancelled.set()
                raise

        client = HttpJsonClient(
            transport=httpx.MockTransport(respond), sleep=wait_before_retry, retries=2
        )
        service = JobSearchService({"arbeitnow": FeedAdapter("arbeitnow", client)})
        request = SearchRequest(
            target_direction="Data Analyst",
            location_unrestricted=True,
            employment_type_unrestricted=True,
            sources=["arbeitnow"],
        )
        async with asyncio.timeout(2):
            result = await service.search_many_async([request], timeout=0.1)

        assert retry_started.is_set()
        assert retry_cancelled.is_set()
        assert len(requested_urls) == 1
        assert not result.raw_jobs
        assert [error.code for error in result.errors] == ["SEARCH_TIMEOUT"]
        assert [(outcome.source, outcome.status) for outcome in result.outcomes] == [
            ("arbeitnow", "unavailable")
        ]

    asyncio.run(scenario())


@pytest.mark.parametrize("source", ["arbeitnow", "careerjet_hk"])
def test_json_adapter_cancellation_preserves_processed_jobs(source: str) -> None:
    async def scenario() -> None:
        records: list[JsonValue] = [
            {
                "id": identity,
                "slug": identity,
                "title": "Data Analyst",
                "company": "Example Co",
                "company_name": "Example Co",
                "url": f"https://example.invalid/jobs/{identity}",
                "location": "Hong Kong",
                "locations": "Hong Kong",
                "description": f"Data Analyst using SQL: {identity}",
            }
            for identity in ("first", "second", "third")
        ]
        payload: dict[str, JsonValue] = (
            {"data": records, "links": {"next": None}}
            if source == "arbeitnow"
            else {"type": "JOBS", "jobs": records, "pages": 1}
        )
        client = FixtureClient({source: payload})
        adapter: SourceAdapter = (
            FeedAdapter(source, client)
            if source == "arbeitnow"
            else CareerjetAdapter("hk", client=client)
        )
        request = SearchRequest(
            target_direction="Data Analyst",
            location_unrestricted=True,
            employment_type_unrestricted=True,
            sources=[source],
        )
        partial = SourceResult()
        operation = asyncio.create_task(adapter.search_async(request, result=partial))
        try:
            async with asyncio.timeout(2):
                while not partial.jobs and not operation.done():
                    await asyncio.sleep(0)
                operation.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await operation

            assert [job.source_job_id for job in partial.jobs] == ["first"]
            assert partial.jobs[0].source == source
            assert partial.jobs[0].description == "Data Analyst using SQL: first"
            assert partial.jobs[0].raw_payload == records[0]
            assert not partial.errors
        finally:
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)

    asyncio.run(scenario())
