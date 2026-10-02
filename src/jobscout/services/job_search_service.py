"""Group 4 synchronous retrieval entry point; no graph/frontend/LLM dependency."""

import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from jobscout.schemas.search import SearchRequest
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
    LEGACY_SOURCES,
    select_sources,
    validate_request,
)
from jobscout.services.job_retrieval.sources import FeedAdapter, SourceAdapter
from jobscout.services.job_retrieval.transport import HttpJsonClient, JsonClient
from jobscout.services.job_retrieval.web_transport import HttpWebClient, WebClient


class JobSearchService:
    """One instance per batch/session. Snapshots retain their actual fetch time."""

    def __init__(
        self,
        adapters: Mapping[str, SourceAdapter] | None = None,
        *,
        client: JsonClient | None = None,
        web_client: WebClient | None = None,
        max_pages: int = 2,
        page_size: int = 20,
        candidate_limit: int = 60,
        result_limit: int = 30,
        detail_limit: int = 5,
    ) -> None:
        if adapters is not None:
            self.adapters = dict(adapters)
        else:
            injected_client = client
            client = client or HttpJsonClient(
                cache_dir=Path(tempfile.gettempdir()) / "jobscout-group4-cache-v1"
            )
            self.adapters = {name: FeedAdapter(name, client) for name in LEGACY_SOURCES}
            public_client = web_client or HttpWebClient()
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

    def search(self, request: SearchRequest) -> SearchResult:
        return self.search_many([request])

    def search_many(self, requests: Sequence[SearchRequest]) -> SearchResult:
        result = SearchResult()
        if not requests:
            result.errors.append(
                workflow_error("SEARCH_INPUT", "At least one SearchRequest is required.")
            )
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
                        "No verified default source for this location; specify a supported region or an explicit source.",
                        request_index=index,
                    )
                )
            for source in sources:
                start = time.perf_counter()
                outcome = SourceOutcome(
                    request_index=index, source=source, target_direction=request.target_direction
                )
                adapter = self.adapters.get(source)
                if adapter is None:
                    result.errors.append(
                        workflow_error(
                            "SEARCH_UNKNOWN_SOURCE",
                            "Unknown job source.",
                            source=source,
                            request_index=index,
                            target_direction=request.target_direction,
                        )
                    )
                    outcome.status = "error"
                else:
                    try:
                        retrieved = adapter.search(request)
                        result.raw_jobs.extend(retrieved.jobs)
                        result.errors.extend(
                            error.model_copy(
                                update={
                                    "details": {**(error.details or {}), "request_index": index}
                                }
                            )
                            for error in retrieved.errors
                        )
                        result.warnings.extend(retrieved.warnings)
                        outcome.candidate_count = retrieved.candidate_count
                        outcome.returned_count = len(retrieved.jobs)
                        outcome.incomplete_count = sum(
                            not all(
                                (
                                    job.title,
                                    job.source_url,
                                    job.company,
                                    job.location,
                                    job.description,
                                )
                            )
                            for job in retrieved.jobs
                        )
                        outcome.excerpt_count = sum(
                            job.raw_payload.get("description_is_excerpt") is True
                            for job in retrieved.jobs
                        )
                        outcome.status = (
                            "partial"
                            if retrieved.errors and retrieved.jobs
                            else "error"
                            if retrieved.errors
                            else "ok"
                            if retrieved.jobs
                            else "empty"
                        )
                    except RetrievalFailure as exc:
                        result.errors.append(
                            workflow_error(
                                exc.code,
                                str(exc),
                                source=source,
                                request_index=index,
                                target_direction=request.target_direction,
                            )
                        )
                        outcome.status = "error"
                outcome.elapsed_seconds = round(time.perf_counter() - start, 4)
                result.outcomes.append(outcome)
        if result.errors and result.raw_jobs:
            result.warnings.append(
                "Partial retrieval: successful jobs retained; inspect errors before downstream processing."
            )
        return result
