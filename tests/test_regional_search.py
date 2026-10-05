"""Geographic routing, native API filters and credential handling; offline."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from jobscout.schemas.search import SearchRequest
from jobscout.services.job_retrieval.careerjet import CareerjetAdapter, careerjet_params
from jobscout.services.job_retrieval.models import RetrievalFailure
from jobscout.services.job_retrieval.planning import select_sources
from jobscout.services.job_retrieval.transport import HttpJsonClient, Page
from jobscout.services.job_search_service import JobSearchService


def req(location: str = "Hong Kong", **updates: object) -> SearchRequest:
    return SearchRequest.model_validate(
        {
            "target_direction": "Data Analyst",
            "location": location,
            "employment_type": "internship",
            **updates,
        }
    )


@pytest.mark.parametrize(
    "location, sources",
    [
        ("Hong Kong", ["jobsdb"]),
        ("香港", ["jobsdb"]),
        ("中国香港", ["jobsdb"]),
        ("Kowloon, Hong Kong", ["jobsdb"]),
        ("深圳", ["zhaopin", "liepin", "shixiseng"]),
        ("Shanghai", ["zhaopin", "liepin", "shixiseng"]),
        ("Beijing, China", ["zhaopin", "liepin", "shixiseng"]),
        ("中国大陆", ["zhaopin", "liepin", "shixiseng"]),
        ("Berlin", []),
        ("Tokyo", []),
    ],
)
def test_regional_routing(location: str, sources: list[str]) -> None:
    assert select_sources(req(location)) == sources


def test_explicit_sources_override_routing() -> None:
    assert select_sources(req(sources=["remotive"])) == ["remotive"]


def test_native_hk_internship_filters() -> None:
    params = careerjet_params(req(), "hk")
    assert params["locale_code"] == "en_HK" and params["contract_type"] == "i"
    assert params["location"] == "Hong Kong" and params["keywords"] == "Data Analyst"
    assert "work_hours" not in params


def test_native_mainland_fulltime_filters_preserve_keywords() -> None:
    params = careerjet_params(
        req("深圳", keywords=["数据分析", "SQL"], employment_type="full-time"), "cn"
    )
    assert params["locale_code"] == "zh_CN" and params["work_hours"] == "f"
    assert params["location"] == "深圳" and params["keywords"] == "数据分析 SQL"


@pytest.mark.parametrize(
    "updates, code",
    [
        ({"location": "Shanghai"}, "SEARCH_REGION_UNSUPPORTED"),
        ({"employment_type": "freelance"}, "SEARCH_FILTER_UNSUPPORTED"),
    ],
)
def test_do_not_silently_broaden_filters(updates: dict[str, object], code: str) -> None:
    with pytest.raises(RetrievalFailure) as exc:
        careerjet_params(SearchRequest.model_validate({**req().model_dump(), **updates}), "hk")
    assert exc.value.code == code


def test_missing_config_is_not_empty_or_foreign_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("CAREERJET_API_KEY", "CAREERJET_USER_IP", "CAREERJET_USER_AGENT"):
        monkeypatch.delenv(key, raising=False)
    with patch("httpx.AsyncHTTPTransport.handle_async_request") as network:
        result = asyncio.run(JobSearchService().search_many_async([req(sources=["careerjet_hk"])]))
    network.assert_not_called()
    assert result.errors[0].code == "SEARCH_CONFIG"
    assert [o.source for o in result.outcomes] == ["careerjet_hk"]
    assert result.outcomes[0].status == "unavailable"


class Client:
    def __init__(self, page: Page) -> None:
        self.page = page
        self.url = ""

    async def get(self, url: str) -> Page:
        self.url = url
        return self.page


def test_mapping_uses_native_filtered_results_and_preserves_raw() -> None:
    client = Client(
        Page(
            payload={
                "type": "JOBS",
                "pages": 2,
                "jobs": [
                    {
                        "title": "Data Analyst Intern",
                        "locations": "Hong Kong",
                        "url": "https://example.invalid/job",
                        "company": "Example",
                        "description": "Original excerpt",
                        "date": "2026-10-01",
                    }
                ],
            },
            fetched_at=datetime.now(UTC),
        )
    )
    result = asyncio.run(CareerjetAdapter("hk", client=client).search_async(req()))
    assert len(result.jobs) == 1 and not result.errors
    assert result.jobs[0].source == "careerjet_hk" and result.jobs[0].expiry_at is None
    assert result.jobs[0].description == "Original excerpt"
    assert parse_qs(urlparse(client.url).query)["contract_type"] == ["i"]
    assert any("bound" in w for w in result.warnings)


def test_location_ambiguity_is_an_error() -> None:
    client = Client(
        Page(payload={"type": "LOCATIONS", "locations": []}, fetched_at=datetime.now(UTC))
    )
    with pytest.raises(RetrievalFailure) as exc:
        asyncio.run(CareerjetAdapter("hk", client=client).search_async(req()))
    assert exc.value.code == "SEARCH_LOCATION_AMBIGUOUS"


def test_authorization_not_in_url_or_redirect_headers() -> None:
    requests: list[httpx.Request] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "example.invalid":
            return httpx.Response(302, headers={"Location": "https://redirect.invalid/feed"})
        return httpx.Response(200, json={"type": "JOBS", "jobs": []})

    asyncio.run(
        HttpJsonClient(authorization="Basic SYNTHETIC", transport=httpx.MockTransport(respond)).get(
            "https://example.invalid"
        )
    )
    assert len(requests) == 2
    assert requests[0].headers["Authorization"] == "Basic SYNTHETIC"
    assert "Authorization" not in requests[1].headers
    assert all("SYNTHETIC" not in str(request.url) for request in requests)
