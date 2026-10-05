"""Bounded asynchronous retrieval with cooperative cancellation."""

import asyncio
import math
import time
from collections.abc import Mapping, Sequence

from jobscout.schemas.search import SearchRequest
from jobscout.services.job_retrieval.async_transport import AsyncHttpWebClient
from jobscout.services.job_retrieval.careerjet import CareerjetAdapter
from jobscout.services.job_retrieval.local_sources import LocalAdapter
from jobscout.services.job_retrieval.models import (
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
        detail_limit: int = 3,
        concurrency: int = 4,
    ) -> None:
        if not 1 <= concurrency <= 16:
            raise ValueError("concurrency must be between 1 and 16")
        self.concurrency = concurrency
        if adapters is not None:
            self.adapters = dict(adapters)
        else:
            injected_client = client
            client = client or HttpJsonClient()
            self.adapters = {name: FeedAdapter(name, client) for name in FEED_SOURCES}
            public_client = async_web_client or AsyncHttpWebClient()
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

    async def search_many_async(
        self, requests: Sequence[SearchRequest], *, timeout: float = 60.0
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
