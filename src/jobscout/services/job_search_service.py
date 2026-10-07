"""Bounded asynchronous retrieval with cooperative cancellation."""

import asyncio
import json
import math
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence

from jobscout.schemas.job import JobPosting, SourceDocument
from jobscout.schemas.search import SearchRequest
from jobscout.services.job_processing_service import process_jobs
from jobscout.services.job_retrieval.async_transport import AsyncHttpWebClient
from jobscout.services.job_retrieval.careerjet import CareerjetAdapter
from jobscout.services.job_retrieval.local_sources import (
    HOSTS,
    LocalAdapter,
    add_detail,
    build_detail_plan,
)
from jobscout.services.job_retrieval.models import (
    RawJob,
    RetrievalFailure,
    SearchResult,
    SourceOutcome,
    workflow_error,
)
from jobscout.services.job_retrieval.planning import (
    DEFAULT_SOURCES,
    FEED_SOURCES,
    select_sources,
    validate_request,
)
from jobscout.services.job_retrieval.sources import FeedAdapter, SourceAdapter, SourceResult
from jobscout.services.job_retrieval.transport import HttpJsonClient, JsonClient
from jobscout.services.job_retrieval.web_transport import AsyncWebClient


class JobSearchService:
    """One instance per batch/session. Snapshots retain their actual fetch time."""

    def __init__(
        self,
        adapters: Mapping[str, SourceAdapter] | None = None,
        *,
        client: JsonClient | None = None,
        async_web_client: AsyncWebClient | None = None,
        max_pages: int = 1,
        page_size: int = 10,
        candidate_limit: int = 60,
        result_limit: int = 10,
        detail_limit: int | None = None,
        concurrency: int = 4,
    ) -> None:
        if not 1 <= concurrency <= 16:
            raise ValueError("concurrency must be between 1 and 16")
        self.concurrency = concurrency
        # The search agent owns the one retry per query/detail action, so this
        # transport must not multiply that action budget with internal retries.
        self.public_client = async_web_client or AsyncHttpWebClient(retries=0)
        if adapters is not None:
            self.adapters = dict(adapters)
        else:
            injected_client = client
            client = client or HttpJsonClient()
            self.adapters = {name: FeedAdapter(name, client) for name in FEED_SOURCES}
            public_client = self.public_client
            self.adapters.update(
                {
                    name: LocalAdapter(
                        name,
                        public_client,
                        max_pages=max_pages,
                        page_size=page_size,
                        candidate_limit=candidate_limit,
                        result_limit=result_limit,
                        detail_limit=detail_limit,
                    )
                    for name in DEFAULT_SOURCES
                }
            )
            self.adapters.update(
                {
                    f"careerjet_{region}": CareerjetAdapter(region, client=injected_client)
                    for region in ("hk", "cn")
                }
            )

    async def fetch_details(
        self, jobs: Sequence[JobPosting], *, timeout: float = 30.0
    ) -> list[JobPosting]:
        """Fetch only source-owned URLs attached to existing candidate identities."""
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("timeout must be finite and nonnegative")
        if timeout == 0:
            return []
        semaphore = asyncio.Semaphore(self.concurrency)

        async def fetch(job: JobPosting) -> JobPosting | None:
            if job.source not in HOSTS:
                return None
            raw = RawJob(
                source=job.source,
                source_url=job.source_url,
                fetched_at=job.fetched_at,
                target_direction=job.target_direction,
                title=job.title,
                company=job.company,
                location=job.location,
                salary=job.salary,
                description=job.description,
                employment_type=job.employment_type,
                posted_at=job.posted_at.isoformat() if job.posted_at else None,
                expiry_at=job.expiry_at.isoformat() if job.expiry_at else None,
                raw_payload={},
            )
            try:
                plan = build_detail_plan(raw)
                if plan is None:
                    return None
                async with semaphore:
                    page = await self.public_client.request_async(
                        plan.url, body=plan.body, headers=plan.headers
                    )
                add_detail(raw, page)
            except RetrievalFailure:
                return None
            document = SourceDocument(
                document_id=f"job:{job.job_id}:detail",
                source=job.source,
                source_url=job.source_url,
                text=raw.description or "",
                fetched_at=page.fetched_at,
            )
            documents = [
                item
                for item in job.source_documents
                if item.document_id
                not in {document.document_id, document.document_id + ":structured"}
            ]
            documents.append(document)
            if raw.raw_payload.get("detail_structured"):
                documents.append(
                    document.model_copy(
                        update={
                            "document_id": document.document_id + ":structured",
                            "text": json.dumps(
                                raw.raw_payload["detail_structured"], ensure_ascii=False
                            ),
                        }
                    )
                )
            normalized = process_jobs(
                [
                    {
                        **job.model_dump(mode="json"),
                        "description": raw.description or job.description,
                        "description_is_excerpt": False,
                        "source_documents": [item.model_dump(mode="json") for item in documents],
                        "location": raw.location or job.location,
                        "employment_type": raw.employment_type or job.employment_type,
                        "posted_at": raw.posted_at,
                        "expiry_at": raw.expiry_at,
                    }
                ]
            ).jobs
            return (
                normalized[0].model_copy(
                    update={
                        "description": raw.description or job.description,
                        "description_is_excerpt": False,
                    },
                    deep=True,
                )
                if normalized
                else None
            )

        tasks = [asyncio.create_task(fetch(job)) for job in jobs]
        if not tasks:
            return []
        try:
            await asyncio.wait(tasks, timeout=timeout)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        return [
            updated
            for task in tasks
            if not task.cancelled() and (updated := task.result()) is not None
        ]

    async def search_many_async(
        self,
        requests: Sequence[SearchRequest],
        *,
        timeout: float = 60.0,
        on_source: Callable[[SearchResult], Awaitable[None]] | None = None,
    ) -> SearchResult:
        """Use one deadline, cancel children, and keep results in request/source order.

        Adapters implement cooperative ``search_async`` with shared partial results.
        The caller supplies the remaining cross-round retrieval/operation budget.
        """
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("timeout must be finite and nonnegative")
        result = SearchResult()
        if not requests:
            result.errors.append(
                workflow_error("SEARCH_INPUT", "At least one SearchRequest is required.")
            )
            return result
        pending: list[tuple[int, SearchRequest, str, SourceResult, SourceOutcome]] = []
        for index, request in enumerate(requests):
            try:
                validate_request(request)
            except RetrievalFailure as exc:
                result.errors.append(workflow_error(exc.code, str(exc), request_index=index))
                continue
            sources = select_sources(request)
            if not sources:
                result.errors.append(
                    workflow_error(
                        "SEARCH_REGION_UNSUPPORTED",
                        "No supported source for this location.",
                        request_index=index,
                    )
                )
            for source in sources:
                pending.append(
                    (
                        index,
                        request,
                        source,
                        SourceResult(),
                        SourceOutcome(
                            request_index=index,
                            source=source,
                            target_direction=request.target_direction,
                        ),
                    )
                )
        semaphore = asyncio.Semaphore(self.concurrency)
        deadline = asyncio.get_running_loop().time() + min(timeout, 60.0)

        async def run_source(
            index: int,
            request: SearchRequest,
            source: str,
            partial: SourceResult,
            outcome: SourceOutcome,
        ) -> None:
            started = time.perf_counter()
            try:
                async with asyncio.timeout_at(deadline), semaphore:
                    if asyncio.get_running_loop().time() >= deadline:
                        raise TimeoutError
                    adapter = self.adapters.get(source)
                    if adapter is None:
                        raise RetrievalFailure("SEARCH_UNKNOWN_SOURCE", "Unknown job source.")
                    retrieved = await adapter.search_async(request, result=partial)
                    if retrieved is not partial:
                        partial.jobs.extend(retrieved.jobs)
                        partial.errors.extend(retrieved.errors)
                        partial.warnings.extend(retrieved.warnings)
                        partial.notices.extend(retrieved.notices)
                        partial.candidate_count = retrieved.candidate_count
            except TimeoutError:
                partial.errors.append(
                    workflow_error(
                        "SEARCH_TIMEOUT",
                        "Source exceeded the remaining retrieval budget.",
                        source=source,
                        request_index=index,
                        target_direction=request.target_direction,
                    )
                )
            except RetrievalFailure as exc:
                partial.errors.append(
                    workflow_error(
                        exc.code,
                        str(exc),
                        source=source,
                        request_index=index,
                        target_direction=request.target_direction,
                    )
                )
            except Exception:
                partial.errors.append(
                    workflow_error(
                        "SEARCH_SOURCE_FAILED",
                        "Source retrieval failed.",
                        source=source,
                        request_index=index,
                        target_direction=request.target_direction,
                    )
                )
            finally:
                outcome.elapsed_seconds = round(time.perf_counter() - started, 4)
                outcome.status = _source_status(partial)
                outcome.candidate_count = partial.candidate_count
                outcome.returned_count = len(partial.jobs)
                outcome.incomplete_count = sum(
                    not all((job.title, job.source_url, job.company, job.location, job.description))
                    for job in partial.jobs
                )
                outcome.excerpt_count = sum(
                    job.description_is_excerpt
                    or job.raw_payload.get("description_is_excerpt") is True
                    for job in partial.jobs
                )
                if on_source is not None:
                    await on_source(
                        SearchResult(
                            raw_jobs=partial.jobs,
                            errors=partial.errors,
                            warnings=partial.warnings,
                            notices=partial.notices,
                            outcomes=[outcome],
                        )
                    )

        tasks = [asyncio.create_task(run_source(*item)) for item in pending]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        for index, _, _, partial, outcome in pending:
            result.raw_jobs.extend(partial.jobs)
            result.errors.extend(
                error.model_copy(
                    update={"details": {**(error.details or {}), "request_index": index}}
                )
                for error in partial.errors
            )
            result.warnings.extend(partial.warnings)
            result.notices.extend(partial.notices)
            result.outcomes.append(outcome)
        if result.errors and result.raw_jobs:
            result.warnings.append(
                "Partial retrieval: successful jobs retained; source diagnostics available."
            )
        return result


def _failure_status(code: str) -> str:
    if code in {"SEARCH_AUTH", "SEARCH_RATE_LIMIT", "SEARCH_SOURCE_REJECTED"}:
        return "blocked"
    return "unavailable"


def _source_status(result: SourceResult) -> str:
    if result.jobs:
        return "partial" if result.errors else "ok"
    if result.errors:
        return (
            "blocked"
            if any(_failure_status(error.code) == "blocked" for error in result.errors)
            else "unavailable"
        )
    return "empty"
