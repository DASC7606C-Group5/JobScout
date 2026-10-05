"""Source field mapping and conservative retrieval filters only."""

from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlencode, urlparse

from pydantic import JsonValue, ValidationError

from jobscout.schemas.errors import WorkflowError
from jobscout.schemas.search import SearchRequest

from .models import RawJob, RetrievalFailure, workflow_error
from .planning import EMPLOYMENT_ALIASES, matches_text, normalized, plan_source_query
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


class SourceAdapter(Protocol):
    def search(self, request: SearchRequest) -> SourceResult: ...


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
        "employment_type": next(
            (
                kind
                for kind, aliases in EMPLOYMENT_ALIASES.items()
                if any(
                    isinstance(label, str) and normalized(label) in aliases
                    for label in (
                        [job_types]
                        if isinstance(job_types, str)
                        else job_types
                        if isinstance(job_types, list)
                        else []
                    )
                )
            ),
            None,
        ),
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
    query = plan_source_query(request, job.source)
    text = f"{job.title or ''} {job.description or ''}"
    if not all(matches_text(text, phrase) for phrase in query.keywords):
        return False
    if query.location and not matches_text(job.location or "", query.location):
        return False
    types = (
        job.raw_payload.get("job_type")
        if job.source == "remotive"
        else job.raw_payload.get("job_types")
    )
    labels = [types] if isinstance(types, str) else types if isinstance(types, list) else []
    if not request.employment_type_unrestricted:
        aliases = next(
            v for k, v in EMPLOYMENT_ALIASES.items() if normalized(k) == query.employment_type
        )
        if not any(isinstance(t, str) and normalized(t) in aliases for t in labels):
            return False
    if request.work_mode:
        # remote=false cannot distinguish onsite from hybrid: never infer it.
        if normalized(request.work_mode) != "remote":
            return False
        if job.source != "remotive" and job.raw_payload.get("remote") is not True:
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

    def search(self, request: SearchRequest) -> SourceResult:
        result = SourceResult()
        label = f"{self.name}/{request.target_direction}"
        result.warnings.append(
            f"{label}: bounded feed; keyword AND phrases, location and employment type filtered locally; unknown hard fields excluded."
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
        if request.work_mode and normalized(request.work_mode) != "remote":
            result.warnings.append(
                f"{label}: cannot verify onsite/hybrid mode; no candidates returned from this source."
            )
            return result
        pages = 1 if self.name == "remotive" else self.max_pages
        for number in range(1, pages + 1):
            query = plan_source_query(
                request, self.name, page=number, candidate_limit=self.candidate_limit
            )
            try:
                if number in self._failures:
                    raise self._failures[number]
                page = self._pages.get(number)
                if page is None:
                    page = self.client.get(URLS[self.name] + "?" + urlencode(query.params))
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
            for index, record in enumerate(records[:remaining]):
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
                        result.warnings.append(
                            f"{label}: result limit {self.result_limit} reached; results are not exhaustive."
                        )
                        return result
            if result.candidate_count >= self.candidate_limit:
                result.warnings.append(
                    f"{label}: candidate limit {self.candidate_limit} reached; results are not exhaustive."
                )
                break
            if self.name == "arbeitnow":
                links = page.payload.get("links")
                if not isinstance(links, dict) or "next" not in links:
                    result.warnings.append(
                        f"{label}: pagination metadata missing; stopped after page {number}."
                    )
                    break
                if not links["next"]:
                    break
                if number == pages:
                    result.warnings.append(
                        f"{label}: page limit {pages} reached; results are not exhaustive."
                    )
                # Generate page URLs ourselves; never follow arbitrary response URLs.
        return result
