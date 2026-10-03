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
    return {
        "raw_jobs": [job.model_dump(mode="json") for job in result.raw_jobs],
        "errors": result.errors,
        "warnings": result.warnings,
    }
