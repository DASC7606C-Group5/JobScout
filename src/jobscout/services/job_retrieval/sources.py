"""Source field mapping and conservative retrieval filters only."""

import asyncio
from dataclasses import dataclass, field
from typing import Protocol, get_args
from urllib.parse import urlencode, urlparse

from pydantic import JsonValue, ValidationError

from jobscout.schemas.errors import WorkflowError
from jobscout.schemas.notices import ApplicantNotice
from jobscout.schemas.profile import EmploymentType
from jobscout.schemas.search import SearchRequest
from jobscout.services.notice_service import make_notice

from .employment import source_employment_label
from .models import RawJob, RetrievalFailure, workflow_error
from .planning import matches_text, normalized, plan_source_query
from .transport import JsonClient, Page

URLS = {
    "remotive": "https://remotive.com/api/remote-jobs",
    "arbeitnow": "https://www.arbeitnow.com/api/job-board-api",
}


@dataclass
class SourceResult:
    jobs: list[RawJob] = field(default_factory=list)
    errors: list[WorkflowError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    candidate_count: int = 0
    notices: list[ApplicantNotice] = field(default_factory=list)


class SourceAdapter(Protocol):
    async def search_async(
        self, request: SearchRequest, *, result: SourceResult | None = None
    ) -> SourceResult: ...


def map_job(source: str, record: dict[str, JsonValue], page: Page, direction: str) -> RawJob:
    """Keep absent values null and source date representations unchanged."""
    type_field = "job_type" if source == "remotive" else "job_types"
    job_types = record.get(type_field)
    if job_types is not None:
        valid = (
            isinstance(job_types, str)
            if source == "remotive"
            else (isinstance(job_types, list) and all(isinstance(t, str) for t in job_types))
        )
        if not valid:
            raise RetrievalFailure("SEARCH_RESPONSE_FORMAT", "Invalid employment type field.")
    if (
        source == "arbeitnow"
        and record.get("remote") is not None
        and not isinstance(record["remote"], bool)
    ):
        raise RetrievalFailure("SEARCH_RESPONSE_FORMAT", "Invalid remote flag.")
    source_id = record.get("id" if source == "remotive" else "slug")
    if source_id is not None and (
        isinstance(source_id, bool) or not isinstance(source_id, (int, str))
    ):
        raise RetrievalFailure("SEARCH_RESPONSE_FORMAT", "Invalid source job ID.")
    data: dict[str, object] = {
        "source": source,
        "source_job_id": str(source_id) if source_id is not None else None,
        "source_url": record.get("url"),
        "fetched_at": page.fetched_at,
        "target_direction": direction,
        "title": record.get("title"),
        "company": record.get("company_name"),
        "description": record.get("description"),
        "employment_type": source_employment_label(job_types),
        "salary": None if record.get("salary") == "" else record.get("salary"),
        "location": record.get(
            "candidate_required_location" if source == "remotive" else "location"
        ),
        "posted_at": record.get("publication_date" if source == "remotive" else "created_at"),
        "expiry_at": record.get("expiry_at"),
        "raw_payload": record,
    }
    try:
        job = RawJob.model_validate(data)
    except ValidationError as exc:
        raise RetrievalFailure("SEARCH_RESPONSE_FORMAT", "Invalid source job field types.") from exc
    if job.source_url:
        try:
            parsed = urlparse(job.source_url)
        except ValueError as exc:
            raise RetrievalFailure("SEARCH_RESPONSE_FORMAT", "Invalid source link.") from exc
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise RetrievalFailure("SEARCH_RESPONSE_FORMAT", "Invalid source link.")
    return job


def matches_request(job: RawJob, request: SearchRequest) -> bool:
    """Reject known location, employment or work-mode mismatches; check unclear text later."""
    from jobscout.services.location_service import get_location_catalog, within

    query = plan_source_query(request, job.source)
    wanted = request.location_ref
    actual = get_location_catalog().find(job.location or "")
    if wanted is not None and len(actual) == 1:
        if not within(actual[0], wanted) and not within(wanted, actual[0]):
            return False
    if (
        not request.employment_type_unrestricted
        and job.employment_type in get_args(EmploymentType)
        and normalized(job.employment_type or "") != query.employment_type
    ):
        return False
    if request.work_mode:
        mode = normalized(request.work_mode)
        if job.source == "remotive" and mode in {"on site", "onsite"}:
            return False
        if mode == "remote" and job.raw_payload.get("remote") is False:
            return False
    return True


class FeedAdapter:
    def __init__(
        self,
        name: str,
        client: JsonClient,
        *,
        max_pages: int = 1,
        candidate_limit: int = 1000,
        result_limit: int = 10,
    ) -> None:
        if (
            name not in URLS
            or not 1 <= max_pages <= 5
            or not 1 <= candidate_limit <= 5000
            or not 1 <= result_limit <= 500
        ):
            raise ValueError("Invalid source or retrieval bounds")
        self.name, self.client = name, client
        self.max_pages, self.candidate_limit, self.result_limit = (
            max_pages,
            candidate_limit,
            result_limit,
        )
        self._pages: dict[int, Page] = {}
        self._failures: dict[int, RetrievalFailure] = {}
        self._page_locks: dict[int, asyncio.Lock] = {}

    async def search_async(
        self, request: SearchRequest, *, result: SourceResult | None = None
    ) -> SourceResult:
        result = SourceResult() if result is None else result
        label = f"{self.name}/{request.target_direction}"
        result.warnings.append(
            f"{label}: fetched a limited set of jobs; known work-condition mismatches excluded, unclear conditions kept for model review."
        )
        if self.name == "remotive":
            result.warnings.append(
                f"{label}: remote-only source; retain Remotive attribution/link; source publication is delayed 24 hours."
            )
        else:
            result.warnings.append(
                f"{label}: Europe-focused feed; no guaranteed Hong Kong coverage."
            )
        if request.salary_range:
            result.warnings.append(
                f"{label}: salary_range is an optional preference and is not applied; Group 6 must evaluate it."
            )
        pages = 1 if self.name == "remotive" else self.max_pages
        for number in range(1, pages + 1):
            query = plan_source_query(
                request, self.name, page=number, candidate_limit=self.candidate_limit
            )
            try:
                async with self._page_locks.setdefault(number, asyncio.Lock()):
                    if number in self._failures:
                        raise self._failures[number]
                    page = self._pages.get(number)
                    if page is None:
                        try:
                            page = await self.client.get(
                                URLS[self.name] + "?" + urlencode(query.params)
                            )
                        except RetrievalFailure as exc:
                            self._failures[number] = exc
                            raise
                        self._pages[number] = page
                key = "jobs" if self.name == "remotive" else "data"
                records = page.payload.get(key)
                if not isinstance(records, list):
                    raise RetrievalFailure("SEARCH_RESPONSE_FORMAT", f"Expected '{key}' array.")
            except RetrievalFailure as exc:
                self._failures[number] = exc
                result.errors.append(
                    workflow_error(
                        exc.code,
                        str(exc),
                        source=self.name,
                        target_direction=request.target_direction,
                        page=number,
                    )
                )
                break
            if page.cached:
                result.warnings.append(
                    f"{label}: using cached page {number}, fetched_at={page.fetched_at.isoformat()}."
                )
            remaining = self.candidate_limit - result.candidate_count
            # Use shared keywords to prioritize fetching jobs, not to decide whether they fit.
            prioritized = sorted(
                enumerate(records[:remaining]),
                key=lambda indexed: (
                    sum(
                        matches_text(
                            f"{indexed[1].get('title', '')} {indexed[1].get('description', '')}",
                            phrase,
                        )
                        for phrase in query.keywords
                    )
                    if isinstance(indexed[1], dict)
                    else 0
                ),
                reverse=True,
            )
            for index, record in prioritized:
                await asyncio.sleep(0)
                result.candidate_count += 1
                try:
                    if not isinstance(record, dict) or not record:
                        raise RetrievalFailure(
                            "SEARCH_RESPONSE_FORMAT", "Expected nonempty job object."
                        )
                    job = map_job(self.name, record, page, request.target_direction)
                except RetrievalFailure as exc:
                    result.errors.append(
                        workflow_error(
                            exc.code,
                            str(exc),
                            source=self.name,
                            target_direction=request.target_direction,
                            page=number,
                            record_index=index,
                        )
                    )
                    continue
                if matches_request(job, request):
                    if any(
                        getattr(job, name) is None
                        for name in ("source_url", "title", "company", "description")
                    ):
                        result.warnings.append(
                            f"{label}: record {index} has missing core fields; nulls retained."
                        )
                    result.jobs.append(job)
                    if len(result.jobs) >= self.result_limit:
                        result.notices.append(make_notice("coverage_limited", source=self.name))
                        result.warnings.append(
                            f"{label}: result limit {self.result_limit} reached; results are not exhaustive."
                        )
                        return result
            if result.candidate_count >= self.candidate_limit:
                result.notices.append(make_notice("coverage_limited", source=self.name))
                result.warnings.append(
                    f"{label}: candidate limit {self.candidate_limit} reached; results are not exhaustive."
                )
                break
            if self.name == "arbeitnow":
                links = page.payload.get("links")
                if not isinstance(links, dict) or "next" not in links:
                    result.notices.append(make_notice("coverage_limited", source=self.name))
                    result.warnings.append(
                        f"{label}: pagination metadata missing; stopped after page {number}."
                    )
                    break
                if not links["next"]:
                    break
                if number == pages:
                    result.notices.append(make_notice("coverage_limited", source=self.name))
                    result.warnings.append(
                        f"{label}: page limit {pages} reached; results are not exhaustive."
                    )
                # Generate page URLs ourselves; never follow arbitrary response URLs.
        return result
