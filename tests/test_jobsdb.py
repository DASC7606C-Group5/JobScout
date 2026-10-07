"""JobsDB frontend API contracts, complete descriptions and blocked responses."""

import asyncio
import json
import time
from datetime import UTC, datetime
from itertools import pairwise

import httpx
import pytest

from jobscout.schemas.job import JobPosting, SourceDocument
from jobscout.schemas.search import SearchRequest
from jobscout.services.job_retrieval.async_transport import AsyncHttpWebClient
from jobscout.services.job_retrieval.local_sources import add_detail, build_detail_plan
from jobscout.services.job_retrieval.models import RawJob, RetrievalFailure
from jobscout.services.job_retrieval.web_transport import WebPage
from jobscout.services.job_search_service import JobSearchService

STAMP = datetime(2026, 10, 8, tzinfo=UTC)
DESCRIPTION = "<h2>Requirements</h2><p>Use SQL &amp; Python.</p><p>Exact final requirement.</p>"


def detail(identifier: str = "123", content: object = DESCRIPTION) -> dict[str, object]:
    return {"data": {"jobDetails": {"job": {"id": identifier, "content": content}}}}


def candidate(**updates: object) -> RawJob:
    return RawJob.model_validate(
        {
            "source": "jobsdb",
            "source_job_id": "123",
            "source_url": "https://hk.jobsdb.com/job/123",
            "target_direction": "Analyst",
            "fetched_at": STAMP,
            "description": "Original excerpt",
            "description_is_excerpt": True,
            "raw_payload": {},
            **updates,
        }
    )


def test_search_and_later_details_use_graphql_and_preserve_source_documents() -> None:
    seen: list[tuple[str, str]] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path == "/api/jobsearch/v5/search":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "123",
                            "title": "Analyst",
                            "teaser": "Original excerpt",
                            "locations": [{"label": "Hong Kong", "countryCode": "HK"}],
                        }
                    ]
                },
            )
        if request.url.path == "/graphql":
            body = json.loads(request.content)
            assert body["operationName"] == "jobDetails"
            assert body["variables"] == {"jobId": "123"}
            return httpx.Response(200, json=detail())
        return httpx.Response(403, headers={"cf-mitigated": "challenge"})

    async def scenario() -> None:
        client = AsyncHttpWebClient(transport=httpx.MockTransport(respond), interval=0, retries=0)
        service = JobSearchService(async_web_client=client)
        result = await service.search_many_async(
            [
                SearchRequest(
                    target_direction="Analyst",
                    location_unrestricted=True,
                    employment_type_unrestricted=True,
                    sources=["jobsdb"],
                )
            ]
        )
        assert not result.errors
        assert [job.source_job_id for job in result.raw_jobs] == ["123"]
        job = result.raw_jobs[0]
        assert job.description == "Requirements Use SQL & Python. Exact final requirement."
        assert job.description_is_excerpt is False
        assert job.raw_payload["listing_description"] == "Original excerpt"
        assert job.raw_payload["detail_html"] == DESCRIPTION
        assert result.outcomes[0].excerpt_count == 0
        assert job.source_url is not None

        original = JobPosting(
            job_id="stable-applicant-candidate",
            source="jobsdb",
            source_url=job.source_url,
            title="Analyst",
            company="Example",
            location="Hong Kong",
            target_direction="Analyst",
            fetched_at=STAMP,
            description="Original excerpt",
            description_is_excerpt=True,
            source_documents=[
                SourceDocument(
                    document_id="original-listing",
                    source="jobsdb",
                    source_url=job.source_url,
                    text="Original excerpt",
                    fetched_at=STAMP,
                    is_excerpt=True,
                )
            ],
        )
        original_json = original.model_dump_json()
        updated = await service.fetch_details([original])
        assert [item.job_id for item in updated] == [original.job_id]
        assert updated[0].description == job.description
        assert updated[0].description_is_excerpt is False
        documents = {item.document_id: item for item in updated[0].source_documents}
        assert documents["original-listing"].text == "Original excerpt"
        assert documents[f"job:{original.job_id}:detail"].text == job.description
        assert documents[f"job:{original.job_id}:detail"].is_excerpt is False
        assert original.model_dump_json() == original_json

    asyncio.run(scenario())
    assert seen == [("GET", "/api/jobsearch/v5/search"), ("POST", "/graphql")]


@pytest.mark.parametrize(
    "response, code",
    [
        (detail(identifier="456"), "SEARCH_RESPONSE_FORMAT"),
        (detail(content=None), "SEARCH_RESPONSE_FORMAT"),
        (detail(content=123), "SEARCH_RESPONSE_FORMAT"),
        (detail(content="<script>hidden</script>"), "SEARCH_RESPONSE_FORMAT"),
        ({"data": {"jobDetails": None}}, "SEARCH_RESPONSE_FORMAT"),
        (
            {**detail(), "errors": [{"message": "private server response"}]},
            "SEARCH_SOURCE_REJECTED",
        ),
    ],
)
def test_invalid_details_do_not_replace_the_listing(response: dict[str, object], code: str) -> None:
    job = candidate()
    original = job.model_dump_json()
    with pytest.raises(RetrievalFailure) as failure:
        add_detail(job, WebPage(json.dumps(response), STAMP))
    assert failure.value.code == code
    assert "private server response" not in str(failure.value)
    assert job.model_dump_json() == original


@pytest.mark.parametrize(
    "url, identifier",
    [
        ("https://example.invalid/job/123", "123"),
        ("https://hk.jobsdb.com/job/456", "123"),
        ("https://hk.jobsdb.com/graphql", "123"),
        ("https://hk.jobsdb.com/job/not-an-id", "not-an-id"),
    ],
)
def test_detail_plan_rejects_untrusted_or_mismatched_job_urls(url: str, identifier: str) -> None:
    with pytest.raises(RetrievalFailure) as failure:
        build_detail_plan(candidate(source_url=url, source_job_id=identifier))
    assert failure.value.code == "SEARCH_RESPONSE_FORMAT"


@pytest.mark.parametrize("status", [200, 403, 503])
def test_cloudflare_challenge_is_not_retried_or_cached(status: int) -> None:
    calls = 0

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                status,
                headers={"cf-mitigated": "challenge"},
                text="<html>Just a moment...</html>",
            )
        return httpx.Response(200, json=detail())

    async def scenario() -> None:
        client = AsyncHttpWebClient(transport=httpx.MockTransport(respond), interval=0)
        with pytest.raises(RetrievalFailure) as failure:
            await client.request_async("https://hk.jobsdb.com/graphql", body={"jobId": "123"})
        assert failure.value.code == "SEARCH_AUTH"
        assert calls == 1
        page = await client.request_async("https://hk.jobsdb.com/graphql", body={"jobId": "123"})
        assert not page.cached
        assert json.loads(page.text) == detail()

    asyncio.run(scenario())
    assert calls == 2


def test_jobsdb_requests_share_the_rate_limit_across_clients() -> None:
    request_times: list[float] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        request_times.append(time.monotonic())
        return httpx.Response(200, json=detail())

    async def scenario() -> None:
        clients = [
            AsyncHttpWebClient(transport=httpx.MockTransport(respond), interval=0.05)
            for _ in range(3)
        ]
        await asyncio.gather(
            *(client.request_async("https://hk.jobsdb.com/graphql") for client in clients)
        )

    asyncio.run(scenario())
    assert len(request_times) == 3
    assert all(later - earlier >= 0.04 for earlier, later in pairwise(request_times))
