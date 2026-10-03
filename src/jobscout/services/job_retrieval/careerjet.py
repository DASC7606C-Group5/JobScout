"""Careerjet v4 regional search. Requires publisher credentials for live calls."""

import base64
import ipaddress
import os
from urllib.parse import urlencode, urlparse

from pydantic import ValidationError

from jobscout.schemas.search import SearchRequest

from .models import RawJob, RetrievalFailure
from .planning import location_region, normalized, plan_keywords, validate_request
from .sources import SourceResult
from .transport import HttpJsonClient, JsonClient

ENDPOINT = "https://search.api.careerjet.net/v4/query"


def careerjet_params(request: SearchRequest, region: str, page: int = 1) -> dict[str, str | int]:
    validate_request(request)
    if region not in {"hk", "cn"}:
        raise RetrievalFailure("SEARCH_REGION_UNSUPPORTED", "Unsupported Careerjet region.")
    actual = location_region(request.location)
    if not request.location_unrestricted and actual != region:
        raise RetrievalFailure(
            "SEARCH_REGION_UNSUPPORTED",
            "Location does not match the selected regional source; use a recognized city/country.",
        )
    params: dict[str, str | int] = {
        "locale_code": "en_HK" if region == "hk" else "zh_CN",
        "keywords": " ".join(plan_keywords(request)),
        "page": page,
        "page_size": 50,
        "sort": "relevance",
        "fragment_size": 1000,
    }
    if request.location and request.location.strip().casefold() not in {
        "hk",
        "cn",
        "china",
        "中国",
        "中國",
        "香港",
        "hong kong",
    }:
        params["location"] = request.location
    else:
        params["location"] = "Hong Kong" if region == "hk" else "China"
    employment = normalized(request.employment_type)
    if employment in {"full time", "part time"}:
        params["work_hours"] = "f" if employment == "full time" else "p"
    elif employment in {"internship", "contract"}:
        params["contract_type"] = "i" if employment == "internship" else "c"
    else:
        raise RetrievalFailure(
            "SEARCH_FILTER_UNSUPPORTED", "Careerjet has no verified freelance filter."
        )
    if request.work_mode:
        raise RetrievalFailure(
            "SEARCH_FILTER_UNSUPPORTED",
            "Careerjet v4 has no documented work-mode filter; refusing to broaden it.",
        )
    return params


class CareerjetAdapter:
    def __init__(self, region: str, *, client: JsonClient | None = None) -> None:
        self.region = region
        self.name = f"careerjet_{region}"
        self.client = client

    def search(self, request: SearchRequest) -> SourceResult:
        params = careerjet_params(request, self.region)
        client = self.client
        if client is None:
            key = os.environ.get("CAREERJET_API_KEY", "").strip()
            user_ip = os.environ.get("CAREERJET_USER_IP", "").strip()
            user_agent = os.environ.get("CAREERJET_USER_AGENT", "").strip()
            if not key or not user_ip or not user_agent:
                raise RetrievalFailure(
                    "SEARCH_CONFIG",
                    "Careerjet requires CAREERJET_API_KEY, CAREERJET_USER_IP and CAREERJET_USER_AGENT; this is not an empty search result.",
                )
            try:
                ipaddress.ip_address(user_ip)
            except ValueError as exc:
                raise RetrievalFailure(
                    "SEARCH_CONFIG", "CAREERJET_USER_IP must be a valid end-user IP address."
                ) from exc
            params.update(user_ip=user_ip, user_agent=user_agent)
            authorization = "Basic " + base64.b64encode((key + ":").encode()).decode()
            # No disk cache: this request includes end-user IP and authenticated access.
            client = HttpJsonClient(authorization=authorization, retries=1)
        page = client.get(ENDPOINT + "?" + urlencode(params))
        if page.payload.get("type") == "LOCATIONS":
            raise RetrievalFailure(
                "SEARCH_LOCATION_AMBIGUOUS",
                "Careerjet could not resolve one location; clarify the city rather than searching nationwide.",
            )
        records = page.payload.get("jobs")
        if page.payload.get("type") != "JOBS" or not isinstance(records, list):
            raise RetrievalFailure(
                "SEARCH_RESPONSE_FORMAT", "Expected Careerjet JOBS response and jobs array."
            )
        result = SourceResult(candidate_count=min(len(records), 50))
        result.warnings.append(
            f"{self.name}: source-native location/employment filters; description is an excerpt, not guaranteed full JD; first page only."
        )
        if request.employment_type == "internship":
            result.warnings.append(
                f"{self.name}: contract_type=i covers internships/training; inspect source text before recommendation."
            )
        if request.salary_range:
            result.warnings.append(f"{self.name}: optional salary preference is not filtered.")
        for index, record in enumerate(records[:50]):
            try:
                if not isinstance(record, dict):
                    raise ValueError("Invalid record")
                job = RawJob.model_validate(
                    {
                        "source": self.name,
                        "source_url": record.get("url"),
                        "source_job_id": record.get("id"),
                        "fetched_at": page.fetched_at,
                        "target_direction": request.target_direction,
                        "title": record.get("title"),
                        "company": record.get("company"),
                        "location": record.get("locations"),
                        "salary": record.get("salary"),
                        "description": record.get("description"),
                        "posted_at": record.get("date"),
                        "expiry_at": None,
                        "raw_payload": record,
                    }
                )
                if job.source_url:
                    parsed = urlparse(job.source_url)
                    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                        raise ValueError("Invalid link")
                result.jobs.append(job)
            except ValueError, ValidationError:
                from .models import workflow_error

                result.errors.append(
                    workflow_error(
                        "SEARCH_RESPONSE_FORMAT",
                        "Invalid Careerjet job fields.",
                        source=self.name,
                        record_index=index,
                    )
                )
        if page.payload.get("pages", 1) != 1 or len(records) >= 50:
            result.warnings.append(
                f"{self.name}: page/candidate bound reached; results are not exhaustive."
            )
        return result
