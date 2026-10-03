"""Offline regression tests for the four selected website interfaces."""

import json
from datetime import UTC, datetime
from email.message import Message
from http.client import IncompleteRead
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import pytest

from jobscout.graph.nodes.search import search_node
from jobscout.schemas.search import SearchRequest
from jobscout.services.job_retrieval.local_sources import (
    LocalAdapter,
    add_detail,
    build_search_plan,
    clean_field,
    detail_url,
    keyword_evidence,
    map_listing,
    parse_listing,
    passes_filters,
)
from jobscout.services.job_retrieval.mock_web import FixtureWebClient
from jobscout.services.job_retrieval.models import RawJob, RetrievalFailure
from jobscout.services.job_retrieval.web_transport import HttpWebClient, WebPage
from jobscout.services.job_search_service import JobSearchService

FIXTURE = Path(__file__).resolve().parents[1] / "data/group4/mock_local_sources.json"
STAMP = datetime(2026, 10, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("Offline tests must not use network")

    monkeypatch.setattr("jobscout.services.job_retrieval.web_transport.urlopen", blocked)
    monkeypatch.setattr("jobscout.services.job_retrieval.transport.urlopen", blocked)


def req(**updates: object) -> SearchRequest:
    return SearchRequest.model_validate(
        {
            "target_direction": "Data Analyst",
            "location": "上海",
            "employment_type": "internship",
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
    result = JobSearchService(web_client=FixtureWebClient(FIXTURE)).search(
        req(location="Hong Kong" if source == "jobsdb" else "上海", sources=[source])
    )
    assert not result.errors and len(result.raw_jobs) == 1
    job = result.raw_jobs[0]
    assert job.source == source and job.source_url and job.description
    assert job.source_job_id and job.fetched_at == STAMP
    assert job.target_direction == "Data Analyst" and job.raw_payload
    json.loads(result.model_dump_json())


def test_multi_direction_node_serialization_and_routing() -> None:
    result = search_node(
        {
            "session_id": "synthetic",
            "search_requests": [
                req(),
                req(target_direction="Business Analyst"),
                req(location="Hong Kong"),
            ],
        },
        service=JobSearchService(web_client=FixtureWebClient(FIXTURE)),
    )
    assert not result["errors"] and len(result["raw_jobs"]) == 7
    assert {r["source"] for r in result["raw_jobs"]} == {"zhaopin", "liepin", "shixiseng", "jobsdb"}
    assert {r["target_direction"] for r in result["raw_jobs"]} == {
        "Data Analyst",
        "Business Analyst",
    }
    json.dumps(result)


def test_native_params_preserve_explicit_intent() -> None:
    request = req(keywords=["SQL", "Business Intelligence"])
    z = build_search_plan(request, "zhaopin", page=2, page_size=7)
    assert z.body and z.body["S_SOU_FULL_INDEX"] == "SQL Business Intelligence 实习"
    assert z.body["S_SOU_WORK_CITY"] == "538" and z.body["pageIndex"] == 2
    assert z.body["order"] == 0 and z.body["pageSize"] == 7
    liepin = build_search_plan(req(), "liepin", page=2)
    assert liepin.headers["X-Fscp-Trace-Id"] and '"currentPage": 1' in json.dumps(liepin.body)
    s = parse_qs(urlsplit(build_search_plan(req(), "shixiseng").url).query)
    assert s["keyword"] == ["数据分析"] and s["city"] == ["上海"]
    j = parse_qs(
        urlsplit(
            build_search_plan(req(location="Hong Kong", employment_type="full-time"), "jobsdb").url
        ).query
    )
    assert j["where"] == ["Hong Kong"] and j["worktype"] == ["242"]
    assert request.keywords == ["SQL", "Business Intelligence"]


@pytest.mark.parametrize(
    "source, updates, code",
    [
        ("zhaopin", {"location": "Hong Kong"}, "SEARCH_REGION_UNSUPPORTED"),
        ("zhaopin", {"location": "武汉"}, "SEARCH_LOCATION_UNSUPPORTED"),
        ("liepin", {"location": "上海浦东"}, "SEARCH_LOCATION_UNSUPPORTED"),
        ("jobsdb", {"location": "Hong Kong", "work_mode": "remote"}, "SEARCH_FILTER_UNSUPPORTED"),
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
        ("shixiseng", "<html>captcha</html>"),
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


def test_unknown_type_and_internship_are_not_fulltime() -> None:
    request = req(location="Hong Kong", employment_type="full-time")
    job = raw(
        title="Data Analyst Intern",
        raw_payload={"workTypes": ["Full time"], "locations": [{"countryCode": "HK"}]},
    )
    assert not passes_filters(job, request)
    job.title = "Data Analyst"
    assert passes_filters(job, request)
    job.raw_payload["workTypes"] = []
    assert not passes_filters(job, request)


class FailingClient(FixtureWebClient):
    def request(
        self,
        url: str,
        *,
        body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> WebPage:
        if "zhaopin" in url:
            raise RetrievalFailure("SEARCH_TIMEOUT", "Synthetic timeout")
        return super().request(url, body=body, headers=headers)


def test_one_source_failure_keeps_other_sources() -> None:
    result = JobSearchService(web_client=FailingClient(FIXTURE)).search(req())
    assert {j.source for j in result.raw_jobs} == {"liepin", "shixiseng"}
    assert result.errors[0].code == "SEARCH_TIMEOUT"
    assert [o.status for o in result.outcomes] == ["error", "ok", "ok"]


class Pages:
    def __init__(self, pages: list[WebPage | RetrievalFailure]) -> None:
        self.pages = pages

    def request(
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
    result = LocalAdapter(
        "zhaopin", Pages([page, RetrievalFailure("SEARCH_RATE_LIMIT", "limited")])
    ).search(req())
    assert len(result.jobs) == 1
    assert [e.code for e in result.errors] == ["SEARCH_RESPONSE_FORMAT", "SEARCH_RATE_LIMIT"]


def test_detail_failure_retains_listing_excerpt_and_error() -> None:
    page = WebPage(
        '{"data":[{"id":"1","title":"Analyst Intern","teaser":"excerpt","locations":[{"label":"Hong Kong","countryCode":"HK"}]}]}',
        STAMP,
    )
    result = LocalAdapter(
        "jobsdb", Pages([page, RetrievalFailure("SEARCH_AUTH", "denied")]), max_pages=1
    ).search(req(location="Hong Kong"))
    assert result.jobs[0].description == "excerpt"
    assert result.jobs[0].raw_payload["description_is_excerpt"] is True
    assert result.errors[0].code == "SEARCH_AUTH"


@pytest.mark.parametrize(
    "failure, code, calls",
    [
        (TimeoutError(), "SEARCH_TIMEOUT", 2),
        (URLError("private"), "SEARCH_NETWORK", 2),
        (IncompleteRead(b"private", 20), "SEARCH_NETWORK", 2),
        (HTTPError("private", 429, "", Message(), None), "SEARCH_RATE_LIMIT", 1),
        (HTTPError("private", 401, "", Message(), None), "SEARCH_AUTH", 1),
        (HTTPError("private", 403, "", Message(), None), "SEARCH_AUTH", 1),
        (HTTPError("private", 503, "", Message(), None), "SEARCH_HTTP", 2),
    ],
)
def test_web_transport_failure_and_retry_bounds(failure: Exception, code: str, calls: int) -> None:
    with patch(
        "jobscout.services.job_retrieval.web_transport.urlopen", side_effect=failure
    ) as network:
        with pytest.raises(RetrievalFailure) as exc:
            HttpWebClient(sleep=lambda _: None).request("https://example.invalid")
    assert exc.value.code == code and "private" not in str(exc.value)
    assert network.call_count == calls


def test_cache_preserves_timestamp_and_distinguishes_queries() -> None:
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b"{}"
    response.__enter__.return_value.headers = Message()
    with patch(
        "jobscout.services.job_retrieval.web_transport.urlopen", return_value=response
    ) as network:
        client = HttpWebClient(sleep=lambda _: None)
        first = client.request("https://example.invalid", body={"key": "a"})
        second = client.request("https://example.invalid", body={"key": "a"})
        client.request("https://example.invalid", body={"key": "b"})
    assert network.call_count == 2 and second.cached and second.fetched_at == first.fetched_at


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
    result = LocalAdapter("shixiseng", client, max_pages=1, detail_limit=1).search(req())
    assert len(result.jobs) == 1 and result.jobs[0].source_job_id == "2"
    assert result.jobs[0].title and result.jobs[0].description
    assert not result.errors and not client.pages
    assert not any("missing core" in w for w in result.warnings)


def test_shixiseng_does_not_pad_results_with_unreadable_titles() -> None:
    listing = '<div class="intern-wrap" data-intern-id="1"><a href="/intern/1" title="实习&#xf015;">intern</a><span class="city">上海</span></div>'
    result = LocalAdapter(
        "shixiseng", Pages([WebPage(listing, STAMP)]), max_pages=1, detail_limit=0
    ).search(req())
    assert not result.jobs and not result.errors
    assert any("unreadable-title" in w for w in result.warnings)


@pytest.mark.parametrize(
    "title, description, expected",
    [
        ("律师助理实习生", "诉讼文书、法律研究", "no_match"),
        ("业务助理实习", "帮助团队进行商业分析", "matched"),
        ("业务助理实习", None, "unverified"),
    ],
)
def test_lexical_guard_does_not_claim_profile_matching(
    title: str, description: str | None, expected: str
) -> None:
    assert (
        keyword_evidence(
            raw("zhaopin", title=title, description=description),
            req(target_direction="Business Analyst"),
        )
        == expected
    )


def test_explicit_keyword_evidence_requires_all_keywords() -> None:
    job = raw("zhaopin", title="SQL analyst", description="Business Intelligence SQL")
    assert keyword_evidence(job, req(keywords=["SQL", "Business Intelligence"])) == "matched"
    assert keyword_evidence(job, req(keywords=["SQL", "Python"])) == "no_match"
    job.source = "jobsdb"
    assert keyword_evidence(job, req(keywords=["SQL", "Python"])) == "unverified"


def test_low_relevance_complete_description_is_excluded() -> None:
    text = '{"code":200,"data":{"list":[{"name":"律师助理实习生","workCity":"上海","workType":"实习","jobDetailData":{"position":{"desc":{"description":"诉讼文书、法律研究"}}}}]}}'
    result = LocalAdapter("zhaopin", Pages([WebPage(text, STAMP)]), max_pages=1).search(
        req(target_direction="Business Analyst")
    )
    assert not result.jobs and any("lexical keyword" in w for w in result.warnings)


def test_batch_error_request_index_and_completeness_counts() -> None:
    service = JobSearchService(web_client=FailingClient(FIXTURE), detail_limit=0)
    result = service.search_many([req(), req(target_direction="Business Analyst")])
    assert [e.details["request_index"] for e in result.errors if e.details] == [0, 1]
    outcome = next(o for o in result.outcomes if o.source == "liepin")
    assert outcome.incomplete_count == outcome.returned_count == 1


def test_unknown_http_charset_returns_safe_structured_failure() -> None:
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b"{}"
    headers = Message()
    headers["Content-Type"] = "text/html; charset=unsupported-encoding"
    response.__enter__.return_value.headers = headers
    with patch("jobscout.services.job_retrieval.web_transport.urlopen", return_value=response):
        with pytest.raises(RetrievalFailure) as exc:
            HttpWebClient().request("https://example.invalid")
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
    "place, expected", [("上海", True), ("Hong Kong", False), ("Berlin", False), (None, False)]
)
def test_country_query_does_not_accept_unknown_or_foreign_locations(
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
