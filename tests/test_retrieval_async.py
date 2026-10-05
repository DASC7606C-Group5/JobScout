"""Offline, cooperative I/O tests for retrieval deadlines and source outcomes."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from jobscout.schemas.job import FreshnessStatus, JobPosting, SourceDocument
from jobscout.schemas.search import SearchRequest
from jobscout.services.job_retrieval.async_transport import AsyncHttpWebClient
from jobscout.services.job_retrieval.careerjet import careerjet_params
from jobscout.services.job_retrieval.local_sources import build_search_plan
from jobscout.services.job_retrieval.mock_web import FixtureWebClient
from jobscout.services.job_retrieval.models import RawJob, RetrievalFailure
from jobscout.services.job_retrieval.planning import select_sources
from jobscout.services.job_retrieval.sources import SourceResult
from jobscout.services.job_retrieval.web_transport import WebPage
from jobscout.services.job_search_service import JobSearchService

STAMP = datetime(2026, 10, 1, tzinfo=UTC)
FIXTURE = Path(__file__).resolve().parents[1] / "data" / "group4" / "mock_local_sources.json"


def test_detail_enrichment_retains_identity_and_rechecks_explicit_expiry() -> None:
    class DetailClient:
        async def request_async(
            self,
            url: str,
            *,
            body: dict[str, object] | None = None,
            headers: dict[str, str] | None = None,
        ) -> WebPage:
            if url.endswith("blocked"):
                raise RetrievalFailure("SEARCH_AUTH", "Blocked")
            data = {
                "@type": "JobPosting",
                "description": "Open-ended Gleam requirement",
                "datePosted": "2026-09-01",
                "validThrough": "2026-09-30",
                "employmentType": "FULL_TIME",
                "jobLocation": {"address": {"addressLocality": "Shanghai", "addressCountry": "CN"}},
            }
            return WebPage(
                '<script type="application/ld+json">' + json.dumps(data) + "</script>", STAMP
            )

    candidate = JobPosting(
        job_id="stable",
        source="liepin",
        source_url="https://www.liepin.com/job/1",
        title="Engineer",
        company="Acme",
        location="",
        target_direction="Engineer",
        fetched_at=STAMP,
        freshness_status=FreshnessStatus.ACTIVE,
        description="Earlier full job description",
        source_documents=[
            SourceDocument(
                document_id="aaa-original",
                source="liepin",
                source_url="https://www.liepin.com/job/1",
                text="Earlier full job description",
                fetched_at=STAMP,
            )
        ],
    )
    original = candidate.model_dump_json()
    blocked = candidate.model_copy(
        update={"job_id": "blocked", "source_url": "https://www.liepin.com/job/blocked"}
    )
    result = asyncio.run(
        JobSearchService(async_web_client=DetailClient()).fetch_details([candidate, blocked])
    )
    assert [job.job_id for job in result] == ["stable"]
    assert result[0].freshness_status == FreshnessStatus.EXPIRED
    assert result[0].expiry_at == datetime(2026, 9, 30, tzinfo=UTC)
    assert result[0].location == "Shanghai, CN"
    assert result[0].employment_type == "full-time"
    assert result[0].description == "Open-ended Gleam requirement"
    assert result[0].description_is_excerpt is False
    assert any(
        doc.document_id == "aaa-original" and doc.text == "Earlier full job description"
        for doc in result[0].source_documents
    )
    assert any('"validThrough": "2026-09-30"' in doc.text for doc in result[0].source_documents)
    assert candidate.model_dump_json() == original


def test_source_redirect_cannot_fetch_an_untrusted_target() -> None:
    seen: list[str] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    client = AsyncHttpWebClient(transport=httpx.MockTransport(respond), interval=0, retries=0)
    with pytest.raises(RetrievalFailure) as error:
        asyncio.run(client.request_async("https://www.liepin.com/job/1"))
    assert error.value.code == "SEARCH_HTTP"
    assert seen == ["https://www.liepin.com/job/1"]


def request(**updates: object) -> SearchRequest:
    return SearchRequest.model_validate(
        {
            "target_direction": "Data Analyst",
            "location_unrestricted": True,
            "employment_type_unrestricted": True,
            **updates,
        }
    )


class Adapter:
    def __init__(
        self, name: str, delay: float = 0, *, error: str = "", empty: bool = False
    ) -> None:
        self.name = name
        self.delay = delay
        self.error = error
        self.empty = empty
        self.started = False
        self.finished = False
        self.cancelled = False

    async def search_async(
        self, request: SearchRequest, *, result: SourceResult | None = None
    ) -> SourceResult:
        self.started = True
        try:
            await asyncio.sleep(self.delay)
            if self.error:
                raise RetrievalFailure(self.error, "Synthetic safe failure")
            return SourceResult(
                jobs=[]
                if self.empty
                else [
                    RawJob(
                        source=self.name,
                        fetched_at=STAMP,
                        target_direction=request.target_direction,
                        source_url=f"https://example.invalid/{self.name}",
                        title="Data Analyst",
                        company="Example",
                        location="Hong Kong",
                        description="SQL analysis",
                        raw_payload={},
                    )
                ],
                candidate_count=0 if self.empty else 1,
            )
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            self.finished = True


def test_success_timeout_blocked_and_empty_are_distinct() -> None:
    async def scenario() -> None:
        adapters = {
            "ok": Adapter("ok"),
            "slow": Adapter("slow", 10),
            "blocked": Adapter("blocked", error="SEARCH_AUTH"),
            "empty": Adapter("empty", empty=True),
        }
        service = JobSearchService(adapters)
        result = await service.search_many_async([request(sources=list(adapters))], timeout=0.03)
        assert [job.source for job in result.raw_jobs] == ["ok"]
        assert [outcome.status for outcome in result.outcomes] == [
            "ok",
            "unavailable",
            "blocked",
            "empty",
        ]
        assert adapters["slow"].cancelled
        assert all(adapter.finished for adapter in adapters.values())
        assert {error.code for error in result.errors} == {"SEARCH_TIMEOUT", "SEARCH_AUTH"}
        assert all(task is asyncio.current_task() or task.done() for task in asyncio.all_tasks())

    asyncio.run(scenario())


def test_external_cancellation_drains_all_children() -> None:
    async def scenario() -> None:
        adapter = Adapter("slow", 10)
        operation = asyncio.create_task(
            JobSearchService({"slow": adapter}).search_many_async(
                [request(sources=["slow"])],
                timeout=30,
            )
        )
        while not adapter.started:
            await asyncio.sleep(0)
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation
        assert adapter.cancelled and adapter.finished
        assert all(task is asyncio.current_task() or task.done() for task in asyncio.all_tasks())

    asyncio.run(scenario())


def test_zero_remaining_budget_does_not_start_adapter() -> None:
    adapter = Adapter("zero")
    result = asyncio.run(
        JobSearchService({"zero": adapter}).search_many_async(
            [request(sources=["zero"])],
            timeout=0,
        )
    )
    assert not adapter.started
    assert result.errors[0].code == "SEARCH_TIMEOUT"


def test_concurrency_is_bounded_and_loop_remains_responsive() -> None:
    async def scenario() -> None:
        active = 0
        peak = 0
        ticks = 0

        class CountingAdapter(Adapter):
            async def search_async(
                self, request: SearchRequest, *, result: SourceResult | None = None
            ) -> SourceResult:
                nonlocal active, peak
                active += 1
                peak = max(peak, active)
                try:
                    return await super().search_async(request)
                finally:
                    active -= 1

        adapters = {str(index): CountingAdapter(str(index), 0.01) for index in range(6)}
        operation = asyncio.create_task(
            JobSearchService(adapters, concurrency=2).search_many_async(
                [request(sources=list(adapters))],
                timeout=1,
            )
        )
        while not operation.done():
            ticks += 1
            await asyncio.sleep(0.001)
        assert len((await operation).raw_jobs) == 6
        assert peak == 2 and ticks > 2 and active == 0

    asyncio.run(scenario())


def test_unrestricted_employment_has_four_sources_and_no_type_filter() -> None:
    req = request()
    assert select_sources(req) == ["zhaopin", "liepin", "shixiseng", "jobsdb"]
    assert "worktype" not in build_search_plan(req, "jobsdb").url
    assert "contract_type" not in careerjet_params(req, "hk")
    assert "work_hours" not in careerjet_params(req, "cn")
    result = asyncio.run(
        JobSearchService(async_web_client=FixtureWebClient(FIXTURE)).search_many_async([req])
    )
    assert not result.errors
    assert {job.source for job in result.raw_jobs} == set(select_sources(req))


def test_work_mode_is_advisory_for_default_sources() -> None:
    result = asyncio.run(
        JobSearchService(async_web_client=FixtureWebClient(FIXTURE)).search_many_async(
            [
                request(work_mode="remote"),
            ]
        )
    )
    assert result.raw_jobs and not result.errors
    assert any("work_mode is advisory" in warning for warning in result.warnings)


def test_async_http_failure_statuses_and_stream_limit() -> None:
    async def scenario() -> None:
        async def respond(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/large":
                return httpx.Response(200, content=b"a" * 4_000_001)
            return httpx.Response(int(req.url.path[1:]), json={"data": []})

        client = AsyncHttpWebClient(transport=httpx.MockTransport(respond), retries=0, interval=0)
        for path, code in [
            ("/403", "SEARCH_AUTH"),
            ("/429", "SEARCH_RATE_LIMIT"),
            ("/503", "SEARCH_HTTP"),
            ("/large", "SEARCH_RESPONSE_FORMAT"),
        ]:
            with pytest.raises(RetrievalFailure) as exc:
                await client.request_async("https://example.invalid" + path)
            assert exc.value.code == code

    asyncio.run(scenario())


def test_transport_cancellation_closes_inflight_stream() -> None:
    async def scenario() -> None:
        closed = False
        reading = asyncio.Event()

        class SlowStream(httpx.AsyncByteStream):
            async def __aiter__(self):  # type: ignore[no-untyped-def]
                reading.set()
                await asyncio.sleep(30)
                yield b"never"

            async def aclose(self) -> None:
                nonlocal closed
                closed = True

        async def respond(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, stream=SlowStream())

        client = AsyncHttpWebClient(transport=httpx.MockTransport(respond), interval=0)
        operation = asyncio.create_task(client.request_async("https://example.invalid/slow"))
        await reading.wait()
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation
        assert closed

    asyncio.run(scenario())


def test_transport_retry_wait_consumes_search_deadline() -> None:
    async def scenario() -> None:
        calls = 0

        async def respond(req: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(503)

        client = AsyncHttpWebClient(transport=httpx.MockTransport(respond), interval=0)
        result = await JobSearchService(async_web_client=client).search_many_async(
            [
                request(sources=["jobsdb"]),
            ],
            timeout=0.01,
        )
        assert calls == 1
        assert result.errors[0].code == "SEARCH_TIMEOUT"
        assert result.outcomes[0].status == "unavailable"

    asyncio.run(scenario())


def test_default_page_results_and_details_budgets() -> None:
    class Client:
        def __init__(self) -> None:
            self.listings = 0
            self.details = 0

        async def request_async(
            self,
            url: str,
            *,
            body: dict[str, object] | None = None,
            headers: dict[str, str] | None = None,
        ) -> WebPage:
            if "jobsearch" in url:
                self.listings += 1
                assert "pageSize=10" in url
                return WebPage(
                    json.dumps(
                        {
                            "data": [
                                {
                                    "id": index,
                                    "title": "Data Analyst",
                                    "advertiser": {"description": "Example"},
                                    "locations": [{"label": "Hong Kong", "countryCode": "HK"}],
                                    "teaser": "SQL Data Analyst",
                                }
                                for index in range(12)
                            ]
                        }
                    ),
                    STAMP,
                )
            self.details += 1
            return WebPage(
                '<div data-automation="jobAdDetails">Data Analyst SQL full description</div>', STAMP
            )

    client = Client()
    result = asyncio.run(
        JobSearchService(async_web_client=client).search_many_async(
            [
                request(sources=["jobsdb"]),
            ]
        )
    )
    assert not result.errors
    assert len(result.raw_jobs) == 10
    assert client.listings == 1 and client.details == 3
    assert result.outcomes[0].excerpt_count == 7
    assert all(job.employment_type is None for job in result.raw_jobs)


def test_timeout_retains_completed_jobs_inside_source() -> None:
    class Client:
        async def request_async(
            self,
            url: str,
            *,
            body: dict[str, object] | None = None,
            headers: dict[str, str] | None = None,
        ) -> WebPage:
            if "jobsearch" in url:
                return WebPage(
                    json.dumps(
                        {
                            "data": [
                                {"id": i, "title": "Data Analyst", "teaser": "Data Analyst SQL"}
                                for i in range(2)
                            ]
                        }
                    ),
                    STAMP,
                )
            if url.endswith("/1"):
                await asyncio.sleep(10)
            return WebPage('<div data-automation="jobAdDetails">Data Analyst SQL</div>', STAMP)

    result = asyncio.run(
        JobSearchService(async_web_client=Client()).search_many_async(
            [
                request(sources=["jobsdb"]),
            ],
            timeout=0.03,
        )
    )
    assert len(result.raw_jobs) == 1
    assert result.outcomes[0].status == "partial"
    assert result.errors[0].code == "SEARCH_TIMEOUT"


def test_async_search_keeps_jobs_when_another_source_is_blocked() -> None:
    result = asyncio.run(
        JobSearchService(
            {"good": Adapter("good"), "bad": Adapter("bad", error="SEARCH_AUTH")}
        ).search_many_async(
            [request(sources=["good", "bad"])],
        )
    )
    assert result.raw_jobs
    assert result.outcomes[1].status == "blocked"
    assert result.errors[0].code == "SEARCH_AUTH"
    assert (result.errors[0].details or {}).get("source") == "bad"


def test_captcha_is_blocked_not_empty() -> None:
    async def respond(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>captcha</html>")

    result = asyncio.run(
        JobSearchService(
            async_web_client=AsyncHttpWebClient(
                transport=httpx.MockTransport(respond),
                interval=0,
            )
        ).search_many_async([request(sources=["shixiseng"])])
    )
    assert result.outcomes[0].status == "blocked"
    assert result.errors[0].code == "SEARCH_AUTH"
