"""Offline tests; no credentials, network, frontend or full graph required."""

import json
from datetime import UTC, datetime
from email.message import Message
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest
from pydantic import JsonValue

from jobscout.schemas.search import SearchRequest
from jobscout.services.job_retrieval.models import RetrievalFailure
from jobscout.services.job_retrieval.planning import (
    plan_keywords,
    plan_source_query,
    select_sources,
)
from jobscout.services.job_retrieval.sources import FeedAdapter
from jobscout.services.job_retrieval.transport import HttpJsonClient, Page
from jobscout.services.job_search_service import JobSearchService

FETCHED = datetime(2026, 10, 1, tzinfo=UTC)


def request(**updates: object) -> SearchRequest:
    return SearchRequest.model_validate(
        {
            "target_direction": "Data Analyst",
            "location_unrestricted": True,
            "employment_type": "full-time",
            **updates,
        }
    )


def row(**updates: JsonValue) -> dict[str, JsonValue]:
    return {
        "id": 10,
        "slug": "fixture-10",
        "title": "Data Analyst",
        "company_name": "Example Co",
        "url": "https://example.invalid/job/10",
        "description": "Data Analyst and Business Analyst using SQL",
        "candidate_required_location": "Worldwide",
        "location": "Berlin",
        "job_type": "full_time",
        "job_types": ["Full-time"],
        "remote": True,
        **updates,
    }


class Pages:
    def __init__(self, *pages: Page | RetrievalFailure) -> None:
        self.pages = list(pages)
        self.urls: list[str] = []

    def get(self, url: str) -> Page:
        self.urls.append(url)
        value = self.pages.pop(0)
        if isinstance(value, RetrievalFailure):
            raise value
        return value


def page(
    source: str = "remotive",
    records: list[JsonValue] | None = None,
    *,
    next_page: str | None = None,
) -> Page:
    return Page(
        payload={
            "jobs" if source == "remotive" else "data": [row()] if records is None else records,
            "links": {"next": next_page},
        },
        fetched_at=FETCHED,
    )


def service(client: Pages, source: str = "remotive", **bounds: int) -> JobSearchService:
    return JobSearchService({source: FeedAdapter(source, client, **bounds)})


def test_planning_preserves_intent_and_does_not_mutate() -> None:
    req = request(keywords=["Business Intelligence", "SQL"])
    assert plan_keywords(req) == ["Business Intelligence", "SQL"]
    assert plan_keywords(request()) == ["Data Analyst"]
    assert select_sources(req) == ["zhaopin", "liepin", "jobsdb"]
    assert select_sources(request(sources=["missing", "remotive", "remotive"])) == [
        "missing",
        "remotive",
    ]
    assert plan_source_query(req, "remotive").params == {"limit": 1000}
    assert plan_source_query(req, "arbeitnow", page=2).params == {"page": 2}
    assert req.keywords == ["Business Intelligence", "SQL"]
    with pytest.raises(RetrievalFailure, match="Unknown"):
        plan_source_query(req, "missing")


def test_single_direction_preserves_raw_fields_and_time() -> None:
    original = row(publication_date="2026-09-20T12:00:00", extra={"vendor": [1, None]})
    result = service(Pages(page(records=[original]))).search(request(sources=["remotive"]))
    assert not result.errors
    job = result.raw_jobs[0]
    assert (job.source, job.source_url, job.target_direction) == (
        "remotive",
        original["url"],
        "Data Analyst",
    )
    assert job.fetched_at == FETCHED and job.fetched_at.utcoffset() is not None
    assert job.source_job_id == "10" and job.raw_payload == original
    assert job.posted_at == "2026-09-20T12:00:00"
    assert job.salary is None and job.expiry_at is None
    json.loads(result.model_dump_json())


def test_multiple_directions_reuse_snapshot_without_deduplicating() -> None:
    client = Pages(page())
    result = service(client).search_many(
        [
            request(sources=["remotive"]),
            request(target_direction="Business Analyst", sources=["remotive"]),
        ]
    )
    assert [j.target_direction for j in result.raw_jobs] == ["Data Analyst", "Business Analyst"]
    assert len(client.urls) == 1
    assert [o.request_index for o in result.outcomes] == [0, 1]


@pytest.mark.parametrize(
    "records", [[], [row(title="Unrelated", description="Unrelated")], [row(job_type="")]]
)
def test_normal_empty_is_not_source_error(records: list[JsonValue]) -> None:
    result = service(Pages(page(records=records))).search(request(sources=["remotive"]))
    assert not result.raw_jobs and not result.errors
    assert result.outcomes[0].status == "empty"


@pytest.mark.parametrize(
    "updates",
    [
        {"target_direction": " "},
        {"location_unrestricted": False},
        {"location": "Hong Kong"},
        {"employment_type": ""},
        {"employment_type": "random"},
        {"keywords": [" "]},
        {"work_mode": "random"},
    ],
)
def test_invalid_semantic_input_never_calls_source(updates: dict[str, object]) -> None:
    client = Pages()
    result = service(client).search(request(**updates))
    assert result.errors[0].code == "SEARCH_INPUT" and not client.urls


def test_empty_batch() -> None:
    assert JobSearchService({}).search_many([]).errors[0].code == "SEARCH_INPUT"


def test_unknown_source_keeps_known_success() -> None:
    result = service(Pages(page())).search(request(sources=["missing", "remotive"]))
    assert len(result.raw_jobs) == 1
    assert result.errors[0].code == "SEARCH_UNKNOWN_SOURCE"
    assert any("Partial retrieval" in w for w in result.warnings)


def test_partial_source_failure_keeps_other_source() -> None:
    svc = JobSearchService(
        {
            "remotive": FeedAdapter(
                "remotive", Pages(RetrievalFailure("SEARCH_TIMEOUT", "timeout"))
            ),
            "arbeitnow": FeedAdapter("arbeitnow", Pages(page("arbeitnow"))),
        }
    )
    result = svc.search(request(sources=["remotive", "arbeitnow"]))
    assert len(result.raw_jobs) == 1 and result.raw_jobs[0].source == "arbeitnow"
    assert result.errors[0].code == "SEARCH_TIMEOUT"
    assert [o.status for o in result.outcomes] == ["error", "ok"]


@pytest.mark.parametrize("payload", [{}, {"jobs": None}, {"jobs": {}}, {"error": "changed"}])
def test_changed_envelope_is_not_empty(payload: dict[str, JsonValue]) -> None:
    result = service(Pages(Page(payload=payload, fetched_at=FETCHED))).search(
        request(sources=["remotive"])
    )
    assert result.errors[0].code == "SEARCH_RESPONSE_FORMAT"


def test_bad_records_do_not_hide_good_records() -> None:
    result = service(Pages(page(records=["bad", {}, row(title={"changed": True}), row()]))).search(
        request(sources=["remotive"])
    )
    assert len(result.raw_jobs) == 1 and len(result.errors) == 3
    assert result.outcomes[0].status == "partial"


def test_missing_optional_fields_stay_null() -> None:
    data = row()
    for key in ("url", "company_name", "id"):
        del data[key]
    result = service(Pages(page(records=[data]))).search(request(sources=["remotive"]))
    job = result.raw_jobs[0]
    assert job.source_url is None and job.company is None and job.source_job_id is None
    assert any("missing core" in w for w in result.warnings)


@pytest.mark.parametrize("url", ["javascript:alert(1)", "no-link", "https://[bad"])
def test_unsafe_or_invalid_source_url(url: str) -> None:
    result = service(Pages(page(records=[row(url=url)]))).search(request(sources=["remotive"]))
    assert not result.raw_jobs and result.errors[0].code == "SEARCH_RESPONSE_FORMAT"


def test_hong_kong_internship_does_not_become_worldwide_fulltime() -> None:
    result = service(Pages(page())).search(
        request(
            location="Hong Kong",
            location_unrestricted=False,
            employment_type="internship",
            sources=["remotive"],
        )
    )
    assert not result.raw_jobs and not result.errors


def test_hard_location_and_type_match() -> None:
    result = service(
        Pages(page(records=[row(candidate_required_location="Hong Kong", job_type="internship")]))
    ).search(
        request(
            location="Hong Kong",
            location_unrestricted=False,
            employment_type="internship",
            sources=["remotive"],
        )
    )
    assert len(result.raw_jobs) == 1


def test_keyword_and_semantics() -> None:
    result = service(Pages(page())).search(
        request(keywords=["Data Analyst", "Python"], sources=["remotive"])
    )
    assert not result.raw_jobs


def test_work_mode_does_not_infer_onsite_from_false() -> None:
    client = Pages()
    result = service(client, "arbeitnow").search(request(work_mode="onsite", sources=["arbeitnow"]))
    assert not result.raw_jobs and not client.urls
    assert any("cannot verify" in w for w in result.warnings)


def test_remote_and_salary_preference_are_explicit() -> None:
    result = service(
        Pages(page("arbeitnow", [row(remote=False), row(remote=True)])), "arbeitnow"
    ).search(request(work_mode="remote", salary_range="50000", sources=["arbeitnow"]))
    assert len(result.raw_jobs) == 1 and any("salary_range" in w for w in result.warnings)


def test_pagination_does_not_follow_response_url_and_preserves_partial() -> None:
    client = Pages(
        page("arbeitnow", next_page="http://internal.invalid/secret"),
        RetrievalFailure("SEARCH_NETWORK", "network"),
    )
    result = service(client, "arbeitnow").search(request(sources=["arbeitnow"]))
    assert len(result.raw_jobs) == 1 and result.errors[0].code == "SEARCH_NETWORK"
    assert client.urls[-1] == "https://www.arbeitnow.com/api/job-board-api?page=2"


@pytest.mark.parametrize("bound", [{"result_limit": 1}, {"candidate_limit": 1}, {"max_pages": 1}])
def test_bounds_are_reported(bound: dict[str, int]) -> None:
    result = service(
        Pages(page("arbeitnow", [row(), row()], next_page="next")), "arbeitnow", **bound
    ).search(request(sources=["arbeitnow"]))
    assert any("limit" in w for w in result.warnings)


@pytest.mark.parametrize(
    ("failure", "code", "calls"),
    [
        (TimeoutError(), "SEARCH_TIMEOUT", 2),
        (URLError("secret-url"), "SEARCH_NETWORK", 2),
        (URLError(TimeoutError()), "SEARCH_TIMEOUT", 2),
        (HTTPError("secret", 429, "rate", Message(), None), "SEARCH_RATE_LIMIT", 1),
        (HTTPError("secret", 401, "auth", Message(), None), "SEARCH_AUTH", 1),
        (HTTPError("secret", 403, "auth", Message(), None), "SEARCH_AUTH", 1),
        (HTTPError("secret", 500, "server", Message(), None), "SEARCH_HTTP", 2),
        (HTTPError("secret", 400, "bad", Message(), None), "SEARCH_HTTP", 1),
    ],
)
def test_transport_error_classification_and_bounded_retries(
    failure: Exception, code: str, calls: int
) -> None:
    with patch(
        "jobscout.services.job_retrieval.transport.urlopen", side_effect=failure
    ) as open_mock:
        with pytest.raises(RetrievalFailure) as exc:
            HttpJsonClient(sleep=lambda _: None).get("https://example.invalid")
    assert exc.value.code == code and "secret" not in str(exc.value)
    assert open_mock.call_count == calls


@pytest.mark.parametrize(
    "body",
    [b"<html>upstream error</html>", b"[]", b"x" * 8_000_001],
    ids=["html", "array", "oversized"],
)
def test_transport_invalid_json_and_size(body: bytes) -> None:
    response = MagicMock()
    response.__enter__.return_value.read.return_value = body
    with patch("jobscout.services.job_retrieval.transport.urlopen", return_value=response):
        with pytest.raises(RetrievalFailure) as exc:
            HttpJsonClient().get("https://example.invalid")
    assert exc.value.code == "SEARCH_RESPONSE_FORMAT"


def test_disk_cache_preserves_actual_fetch_time(tmp_path: Path) -> None:
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"jobs": []}'
    with patch("jobscout.services.job_retrieval.transport.urlopen", return_value=response) as get:
        original = HttpJsonClient(cache_dir=tmp_path).get("https://example.invalid")
        cached = HttpJsonClient(cache_dir=tmp_path).get("https://example.invalid")
    assert get.call_count == 1 and cached.cached
    assert cached.fetched_at == original.fetched_at


def test_expired_cache_is_not_silently_used_on_failure(tmp_path: Path) -> None:
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"jobs": []}'
    with patch("jobscout.services.job_retrieval.transport.urlopen", return_value=response):
        HttpJsonClient(cache_dir=tmp_path).get("https://example.invalid")
    with patch("jobscout.services.job_retrieval.transport.urlopen", side_effect=TimeoutError()):
        with pytest.raises(RetrievalFailure):
            HttpJsonClient(cache_dir=tmp_path, cache_seconds=0, retries=0).get(
                "https://example.invalid"
            )
