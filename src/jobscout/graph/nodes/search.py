"""Thin search node; Group 3 owns routing and the complete graph."""

from typing import TypedDict

from jobscout.graph.state import AgentState
from jobscout.schemas.errors import WorkflowError
from jobscout.services.job_search_service import JobSearchService


class SearchUpdate(TypedDict):
    raw_jobs: list[dict[str, object]]
    errors: list[WorkflowError]
    warnings: list[str]


def search_node(state: AgentState, *, service: JobSearchService | None = None) -> SearchUpdate:
    result = (service or JobSearchService()).search_many(state.get("search_requests", []))
    # Return only new diagnostics; append reducers preserve history.
    # Replace raw_jobs on rerun; do not append old results or choose routing.
    return {
        "raw_jobs": [job.model_dump(mode="json") for job in result.raw_jobs],
        "errors": result.errors,
        "warnings": result.warnings,
    }
