"""Offline regression tests for the four selected website interfaces."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from jobscout.schemas.search import SearchRequest
from jobscout.services.job_retrieval.async_transport import AsyncHttpWebClient
from jobscout.services.job_retrieval.local_sources import (
    LocalAdapter,
    add_detail,
    build_search_plan,
    clean_field,
    detail_url,
    map_listing,
    parse_listing,
    passes_filters,
)
from jobscout.services.job_retrieval.mock_web import FixtureWebClient
from jobscout.services.job_retrieval.models import RawJob, RetrievalFailure
from jobscout.services.job_retrieval.web_transport import WebPage
from jobscout.services.job_search_service import JobSearchService
from jobscout.services.location_service import get_location_catalog
from tests.location_fixtures import bound_location, catalog_snapshot

FIXTURE = Path(__file__).resolve().parents[1] / "data/group4/mock_local_sources.json"
STAMP = datetime(2026, 10, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("Offline tests must not use network")

    monkeypatch.setattr("httpx.AsyncHTTPTransport.handle_async_request", blocked)
    monkeypatch.setattr("jobscout.services.location_service._catalog", catalog_snapshot())


def req(**updates: object) -> SearchRequest:
    return SearchRequest.model_validate(
        {
            "target_direction": "Data Analyst",
            "location": "上海",
            "employment_type": "internship",
            "location_ref": bound_location(updates.get("location", "上海")),
            **updates,
        }
    )


def raw(source: str = "jobsdb", **updates: object) -> RawJob:
    return RawJob.model_validate(
        {
            "source": source,
            "target_direction": "Data Analyst",
            "fetched_at": STAMP,
            "raw_payload": {},
            **updates,
        }
    )


@pytest.mark.parametrize("source", ["zhaopin", "liepin", "shixiseng", "jobsdb"])
def test_selected_source_fields_and_description(source: str) -> None:
    result = asyncio.run(
        JobSearchService(async_web_client=FixtureWebClient(FIXTURE)).search_many_async(
            [req(location="Hong Kong" if source == "jobsdb" else "上海", sources=[source])]
        )
    )
    assert not result.errors
    assert [job.source_job_id for job in result.raw_jobs] == (
        ["inn_1"] if source == "shixiseng" else ["11", "10"]
    )
    job = result.raw_jobs[0]
    assert job.source == source and job.source_url and job.description
    assert job.source_job_id and job.fetched_at == STAMP
    assert job.target_direction == "Data Analyst" and job.raw_payload
    json.loads(result.model_dump_json())


def test_multi_direction_search_serialization_and_routing() -> None:
    result = asyncio.run(
        JobSearchService(async_web_client=FixtureWebClient(FIXTURE)).search_many_async(
            [req(), req(target_direction="Business Analyst"), req(location="Hong Kong")]
        )
    )
    assert not result.errors
    assert {(job.source, job.target_direction, job.source_job_id) for job in result.raw_jobs} == {
        (source, direction, job_id)
        for source in ("zhaopin", "liepin", "shixiseng", "jobsdb")
        for direction, base_id in (("Data Analyst", 10), ("Business Analyst", 20))
        if source != "jobsdb" or direction == "Data Analyst"
        for job_id in (
            [f"inn_{base_id // 10}"] if source == "shixiseng" else [str(base_id + 1), str(base_id)]
        )
    }
    assert {r.source for r in result.raw_jobs} == {"zhaopin", "liepin", "shixiseng", "jobsdb"}
    assert {r.target_direction for r in result.raw_jobs} == {
        "Data Analyst",
        "Business Analyst",
    }
    json.loads(result.model_dump_json())


def test_native_params_preserve_explicit_intent() -> None:
    request = req(keywords=["SQL", "Business Intelligence"])
    z = build_search_plan(request, "zhaopin", page=2, page_size=7)
    assert z.body and z.body["S_SOU_FULL_INDEX"] == "SQL Business Intelligence 实习"
    assert z.body["S_SOU_WORK_CITY"] == "538" and z.body["pageIndex"] == 2
    assert z.body["order"] == 0 and z.body["pageSize"] == 7
    liepin = build_search_plan(req(), "liepin", page=2)
    assert liepin.headers["X-Fscp-Trace-Id"] and '"currentPage": 1' in json.dumps(liepin.body)
    s = parse_qs(urlsplit(build_search_plan(req(), "shixiseng").url).query)
    assert s["keyword"] == ["Data Analyst"] and s["city"] == ["上海"]
    j = parse_qs(
        urlsplit(
            build_search_plan(req(location="Hong Kong", employment_type="full-time"), "jobsdb").url
        ).query
    )
    assert j["where"] == ["Hong Kong"] and j["worktype"] == ["242"]
    assert request.keywords == ["SQL", "Business Intelligence"]


def test_catalog_city_outside_old_six_and_district_query_keep_identity() -> None:
    wuhan = build_search_plan(req(location="武汉"), "zhaopin")
    assert wuhan.body is not None and wuhan.body["S_SOU_WORK_CITY"] == "736"
    request = req(location="Pudong")
    original = request.model_copy(deep=True)
    assert request.location_ref is not None
    mapped = asyncio.run(get_location_catalog().source_location(request.location_ref, "liepin"))
    plan = build_search_plan(request.model_copy(update={"location_ref": mapped}), "liepin")
    assert mapped.id == "cn:2031" and mapped.level == "district"
    assert plan.body is not None
    condition = plan.body["data"]
    assert isinstance(condition, dict)
    assert condition["mainSearchPcConditionForm"]["city"] == "020"
    assert request == original


@pytest.mark.parametrize(
    "source, updates, code",
    [
        ("zhaopin", {"location": "Hong Kong"}, "SEARCH_REGION_UNSUPPORTED"),
        ("zhaopin", {"location": "Atlantis"}, "SEARCH_LOCATION_UNSUPPORTED"),
        ("liepin", {"location": "上海浦东"}, "SEARCH_LOCATION_UNSUPPORTED"),
        ("shixiseng", {"employment_type": "full-time"}, "SEARCH_FILTER_UNSUPPORTED"),
        ("unknown", {}, "SEARCH_UNKNOWN_SOURCE"),
    ],
)
def test_unsupported_filters_do_not_broaden(
    source: str, updates: dict[str, object], code: str
) -> None:
    with pytest.raises(RetrievalFailure) as exc:
        build_search_plan(req(**updates), source)
    assert exc.value.code == code


@pytest.mark.parametrize(
    "source, text",
    [
        ("zhaopin", '{"code":200,"data":{"list":[]}}'),
        ("liepin", '{"flag":1,"data":{"data":{"jobCardList":[]}}}'),
        ("jobsdb", '{"data":[]}'),
        ("shixiseng", "<main>暂无相关职位</main>"),
    ],
)
def test_confirmed_empty(source: str, text: str) -> None:
    assert parse_listing(source, WebPage(text, STAMP)) == []


@pytest.mark.parametrize(
    "source, text",
    [
        ("zhaopin", '{"code":200}'),
        ("liepin", '{"flag":1}'),
        ("jobsdb", '{"data":{}}'),
        ("zhaopin", "<html>login</html>"),
    ],
)
def test_changed_response_not_empty(source: str, text: str) -> None:
    with pytest.raises(RetrievalFailure) as exc:
        parse_listing(source, WebPage(text, STAMP))
    assert exc.value.code == "SEARCH_RESPONSE_FORMAT"


def test_missing_optional_fields_and_unsafe_link() -> None:
    job = map_listing("zhaopin", {"name": "Data Analyst"}, WebPage("", STAMP), "Data Analyst")
    assert job.company is None and job.salary is None and job.description is None
    for url in ["https://[bad", "https://example.invalid/job/1", "https://hk.jobsdb.com:123/job/1"]:
        with pytest.raises(RetrievalFailure):
            detail_url(raw(source_url=url))


def test_shixiseng_glyphs_and_detail_mapping() -> None:
    assert clean_field("实习&#xf015") is None
    job = raw("shixiseng")
    add_detail(
        job,
        WebPage(
            '<div class="new_job_name">数据分析实习生</div><span class="job_money">200-300/天</span><div class="job_detail">SQL analysis</div><span class="job_position">上海</span>',
            STAMP,
        ),
    )
    assert job.title == "数据分析实习生" and job.salary == "200-300/天" and job.location == "上海"


def test_textual_employment_uncertainty_is_preserved_for_assessment() -> None:
    request = req(location="Hong Kong", employment_type="full-time")
    job = raw(
        title="Data Analyst Intern",
        raw_payload={"workTypes": ["Full time"], "locations": [{"countryCode": "HK"}]},
    )
    assert passes_filters(job, request)
    job.title = "Data Analyst"
    assert passes_filters(job, request)
    job.raw_payload["workTypes"] = []
    assert passes_filters(job, request)


class FailingClient(FixtureWebClient):
    async def request_async(
        self,
        url: str,
        *,
        body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> WebPage:
        if "zhaopin" in url:
            raise RetrievalFailure("SEARCH_TIMEOUT", "Synthetic timeout")
        return await super().request_async(url, body=body, headers=headers)


def test_one_source_failure_keeps_other_sources() -> None:
    result = asyncio.run(
        JobSearchService(async_web_client=FailingClient(FIXTURE)).search_many_async([req()])
    )
    assert {j.source for j in result.raw_jobs} == {"liepin", "shixiseng"}
    assert result.errors[0].code == "SEARCH_TIMEOUT"
    assert [o.status for o in result.outcomes] == ["unavailable", "ok", "ok"]


class Pages:
    def __init__(self, pages: list[WebPage | RetrievalFailure]) -> None:
        self.pages = pages

    async def request_async(
        self,
        url: str,
        *,
        body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> WebPage:
        value = self.pages.pop(0)
        if isinstance(value, RetrievalFailure):
            raise value
        return value


def test_pagination_failure_and_malformed_record_preserve_success() -> None:
    page = WebPage(
        '{"code":200,"data":{"list":[null,{"name":"数据分析实习","jobId":1,"workType":"实习","workCity":"上海"}]}}',
        STAMP,
    )
    result = asyncio.run(
        LocalAdapter(
            "zhaopin", Pages([page, RetrievalFailure("SEARCH_RATE_LIMIT", "limited")]), max_pages=2
        ).search_async(req())
    )
    assert len(result.jobs) == 1
    assert [e.code for e in result.errors] == ["SEARCH_RESPONSE_FORMAT", "SEARCH_RATE_LIMIT"]


def test_detail_failure_retains_listing_excerpt_and_error() -> None:
    page = WebPage(
        '{"data":[{"id":"1","title":"Analyst Intern","teaser":"excerpt","locations":[{"label":"Hong Kong","countryCode":"HK"}]}]}',
        STAMP,
    )
    result = asyncio.run(
        LocalAdapter(
            "jobsdb", Pages([page, RetrievalFailure("SEARCH_AUTH", "denied")]), max_pages=1
        ).search_async(req(location="Hong Kong"))
    )
    assert result.jobs[0].description == "excerpt"
    assert result.jobs[0].raw_payload["description_is_excerpt"] is True
    assert result.errors[0].code == "SEARCH_AUTH"


@pytest.mark.parametrize(
    "failure, code, calls",
    [
        (httpx.ReadTimeout("private"), "SEARCH_TIMEOUT", 2),
        (httpx.ConnectError("private"), "SEARCH_NETWORK", 2),
        (httpx.RemoteProtocolError("private"), "SEARCH_NETWORK", 2),
        (429, "SEARCH_RATE_LIMIT", 1),
        (401, "SEARCH_AUTH", 1),
        (403, "SEARCH_AUTH", 1),
        (503, "SEARCH_HTTP", 2),
    ],
)
def test_web_transport_failure_and_retry_bounds(
    failure: Exception | int, code: str, calls: int
) -> None:
    count = 0

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        if isinstance(failure, Exception):
            raise failure
        return httpx.Response(failure)

    with pytest.raises(RetrievalFailure) as exc:
        asyncio.run(
            AsyncHttpWebClient(transport=httpx.MockTransport(respond), interval=0).request_async(
                "https://example.invalid"
            )
        )
    assert exc.value.code == code and "private" not in str(exc.value)
    assert count == calls


def test_cache_preserves_timestamp_and_distinguishes_queries() -> None:
    count = 0

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        return httpx.Response(200, json={})

    async def scenario() -> None:
        client = AsyncHttpWebClient(transport=httpx.MockTransport(respond), interval=0)
        first = await client.request_async("https://example.invalid", body={"key": "a"})
        second = await client.request_async("https://example.invalid", body={"key": "a"})
        await client.request_async("https://example.invalid", body={"key": "b"})
        assert count == 2 and second.cached and second.fetched_at == first.fetched_at

    asyncio.run(scenario())


def test_verification_response_is_not_normal_empty() -> None:
    with pytest.raises(RetrievalFailure) as exc:
        parse_listing(
            "zhaopin", WebPage('{"code":200,"data":{"isVerification":1,"list":[]}}', STAMP)
        )
    assert exc.value.code == "SEARCH_AUTH"


def test_shixiseng_filters_location_before_spending_detail_budget() -> None:
    listing = '<div class="intern-wrap" data-intern-id="1"><a href="/intern/1" title="实习&#xf015;">intern</a><span class="city">北京</span></div><div class="intern-wrap" data-intern-id="2"><a href="/intern/2" title="实习&#xf015;">intern</a><span class="city">上海</span></div>'
    detail = '<div class="new_job_name">数据分析实习生</div><div class="job_position">上海</div><div class="job_detail">数据分析 SQL</div>'
    client = Pages([WebPage(listing, STAMP), WebPage(detail, STAMP)])
    result = asyncio.run(
        LocalAdapter("shixiseng", client, max_pages=1, detail_limit=1).search_async(req())
    )
    assert len(result.jobs) == 1 and result.jobs[0].source_job_id == "2"
    assert result.jobs[0].title and result.jobs[0].description
    assert not result.errors and not client.pages
    assert not any("missing core" in w for w in result.warnings)


def test_shixiseng_does_not_pad_results_with_unreadable_titles() -> None:
    listing = '<div class="intern-wrap" data-intern-id="1"><a href="/intern/1" title="实习&#xf015;">intern</a><span class="city">上海</span></div>'
    result = asyncio.run(
        LocalAdapter(
            "shixiseng", Pages([WebPage(listing, STAMP)]), max_pages=1, detail_limit=0
        ).search_async(req())
    )
    assert not result.jobs and not result.errors
    assert {(notice.code, notice.source) for notice in result.notices} == {
        ("coverage_limited", "shixiseng")
    }


def test_original_description_survives_retrieval_for_semantic_relevance_review() -> None:
    text = '{"code":200,"data":{"list":[{"name":"律师助理实习生","workCity":"上海","workType":"实习","jobDetailData":{"position":{"desc":{"description":"诉讼文书、法律研究"}}}}]}}'
    result = asyncio.run(
        LocalAdapter("zhaopin", Pages([WebPage(text, STAMP)]), max_pages=1).search_async(
            req(target_direction="Business Analyst")
        )
    )
    assert [job.title for job in result.jobs] == ["律师助理实习生"]
    assert result.jobs[0].description == "诉讼文书、法律研究"


def test_batch_error_request_index_and_completeness_counts() -> None:
    service = JobSearchService(async_web_client=FailingClient(FIXTURE), detail_limit=0)
    result = asyncio.run(
        service.search_many_async([req(), req(target_direction="Business Analyst")])
    )
    assert [e.details["request_index"] for e in result.errors if e.details] == [0, 1]
    outcome = next(o for o in result.outcomes if o.source == "liepin")
    assert [job.source_job_id for job in result.raw_jobs if job.source == "liepin"] == [
        "11",
        "10",
        "21",
        "20",
    ]
    assert outcome.incomplete_count == outcome.returned_count == 2


def test_unknown_http_charset_returns_safe_structured_failure() -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"{}", headers={"Content-Type": "text/html; charset=unsupported-encoding"}
        )

    with pytest.raises(RetrievalFailure) as exc:
        asyncio.run(
            AsyncHttpWebClient(transport=httpx.MockTransport(respond), interval=0).request_async(
                "https://example.invalid"
            )
        )
    assert exc.value.code == "SEARCH_RESPONSE_FORMAT"


def test_shixiseng_company_listing_and_current_detail_selector() -> None:
    page = WebPage(
        '<div class="intern-wrap"><a href="/intern/1" title="数据分析">job</a><div class="intern-detail__company"><a class="title" href="javascript:;">Synthetic Co</a></div></div>',
        STAMP,
    )
    record = parse_listing("shixiseng", page)[0]
    job = map_listing("shixiseng", record, page, "Data Analyst")
    assert job.company == "Synthetic Co"
    add_detail(
        job,
        WebPage(
            '<a class="com-name" href="javascript:;">Detail Co</a><div class="job_detail">数据分析</div>',
            STAMP,
        ),
    )
    assert job.company == "Detail Co"


@pytest.mark.parametrize(
    "place, expected", [("上海", True), ("Hong Kong", False), ("Berlin", True), (None, True)]
)
def test_country_query_rejects_verified_other_region_and_retains_unknown_for_assessment(
    place: str | None, expected: bool
) -> None:
    assert passes_filters(raw("shixiseng", location=place), req(location="China")) is expected


def test_hk_district_alias_checks_country_too() -> None:
    job = raw(
        title="Data Analyst Intern",
        location="Kowloon Bay, Kwun Tong District",
        raw_payload={"locations": [{"countryCode": "HK"}]},
    )
    assert passes_filters(job, req(location="Kowloon, Hong Kong"))
    job.raw_payload["locations"] = [{"countryCode": "SG"}]
    assert not passes_filters(job, req(location="Kowloon, Hong Kong"))
