from typing import TypedDict

from jobscout.graph.state import AgentState
from jobscout.schemas.errors import WorkflowError
from jobscout.services.job_retrieval.models import SearchResult
from jobscout.services.job_search_service import JobSearchService


class SearchUpdate(TypedDict):
    raw_jobs: list[dict[str, object]]
    errors: list[WorkflowError]
    warnings: list[str]
    source_outcomes: list[dict[str, object]]


def search_node(state: AgentState, *, service: JobSearchService | None = None) -> SearchUpdate:
    result = (service or JobSearchService()).search_many(state.get("search_requests", []))
    return _update(result)


async def search_node_async(
    state: AgentState, *, service: JobSearchService | None = None, timeout: float = 60.0
) -> SearchUpdate:
    result = await (service or JobSearchService()).search_many_async(
        state.get("search_requests", []), timeout=timeout
    )
    return _update(result)


def _update(result: SearchResult) -> SearchUpdate:
    return {
        "raw_jobs": [job.model_dump(mode="json") for job in result.raw_jobs],
        "errors": [error for error in result.errors if not (error.details or {}).get("source")],
        "warnings": result.warnings
        + [
            f"Source {error.details.get('source')}: {error.code}"
            for error in result.errors
            if error.details and error.details.get("source")
        ],
        "source_outcomes": [outcome.model_dump(mode="json") for outcome in result.outcomes],
    }
