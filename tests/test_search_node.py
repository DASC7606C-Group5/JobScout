"""Manually constructed AgentState; no dependency on other groups' graph."""

from datetime import UTC, datetime

from jobscout.graph.nodes.search import search_node
from jobscout.graph.state import AgentState
from jobscout.schemas.errors import WorkflowError
from jobscout.schemas.search import SearchRequest
from jobscout.services.job_retrieval.transport import Page
from jobscout.services.job_search_service import JobSearchService


class EmptyClient:
    def get(self, url: str) -> Page:
        return Page(
            payload={"jobs": [], "data": [], "links": {"next": None}}, fetched_at=datetime.now(UTC)
        )


def test_node_returns_only_new_diagnostics_without_mutating_state() -> None:
    old = WorkflowError(code="UPSTREAM", stage="profile", message="example")
    state: AgentState = {
        "session_id": "fixture-session",
        "errors": [old],
        "warnings": ["upstream"],
        "raw_jobs": [{"old": True}],
        "search_requests": [
            SearchRequest(
                target_direction="Data Analyst",
                location_unrestricted=True,
                employment_type="full-time",
                sources=["remotive", "arbeitnow"],
            )
        ],
    }
    update = search_node(state, service=JobSearchService(client=EmptyClient()))
    assert set(update) == {"raw_jobs", "errors", "warnings", "source_outcomes"}
    assert update["raw_jobs"] == []
    assert update["errors"] == []
    assert "upstream" not in update["warnings"]
    assert state["errors"] == [old]
    assert state["raw_jobs"] == [{"old": True}] and state["warnings"] == ["upstream"]


def test_node_missing_requests_returns_input_error() -> None:
    update = search_node({"session_id": "fixture"}, service=JobSearchService({}))
    assert update["errors"][0].code == "SEARCH_INPUT"


def test_node_raw_jobs_are_json_serializable() -> None:
    import json

    from jobscout.services.job_retrieval.transport import FixtureClient

    client = FixtureClient(
        {
            "remotive": {
                "jobs": [
                    {
                        "title": "Data Analyst",
                        "job_type": "full_time",
                        "url": "https://example.invalid/job",
                        "description": "Synthetic fixture",
                    }
                ]
            }
        }
    )
    state: AgentState = {
        "session_id": "fixture",
        "search_requests": [
            SearchRequest(
                target_direction="Data Analyst",
                employment_type="full-time",
                location_unrestricted=True,
                sources=["remotive"],
            )
        ],
    }
    result = search_node(state, service=JobSearchService(client=client))
    assert len(result["raw_jobs"]) == 1
    assert isinstance(result["raw_jobs"][0]["fetched_at"], str)
    json.dumps(result["raw_jobs"])
