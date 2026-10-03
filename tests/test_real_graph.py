"""Integration tests for the production graph wiring."""

from datetime import UTC, datetime
from typing import Any, cast

from langgraph.checkpoint.memory import InMemorySaver

from jobscout.graph.builder import build_graph
from jobscout.graph.nodes import search as search_module
from jobscout.graph.runner import run_workflow
from jobscout.services.job_retrieval.models import RawJob, SearchResult

SESSION_INPUT = {
    "description": "熟悉 Python、FastAPI 和 PostgreSQL",
    "resume": None,
    "target_directions": ["后端开发"],
    "preferences": {
        "location": "香港",
        "location_unrestricted": False,
        "employment_type": "full-time",
        "salary_range": None,
        "work_mode": None,
        "industry": None,
    },
}


class StubSearchService:
    def search_many(self, requests: object) -> SearchResult:
        return SearchResult(
            raw_jobs=[
                RawJob(
                    source="stub",
                    source_url="https://example.test/jobs/1",
                    fetched_at=datetime.now(UTC),
                    target_direction="后端开发",
                    source_job_id="1",
                    title="Python Backend Engineer",
                    company="Example",
                    location="香港",
                    salary="HKD 30000",
                    description="Build Python and FastAPI services.",
                    raw_payload={},
                )
            ]
        )


def make_graph() -> Any:
    return build_graph(checkpointer=InMemorySaver())


def test_real_graph_completes_with_all_business_nodes(monkeypatch: Any) -> None:
    monkeypatch.setattr(search_module, "JobSearchService", StubSearchService)

    result = run_workflow(make_graph(), "real-complete", input_data=dict(SESSION_INPUT))

    assert result["outcome"] == "completed"
    state = result["state"]
    assert state["current_stage"] == "completed"
    assert state["search_requests"]
    assert state["normalized_jobs"]
    assert state["recommendation"] is not None


def test_real_graph_pauses_and_resumes_clarification(monkeypatch: Any) -> None:
    monkeypatch.setattr(search_module, "JobSearchService", StubSearchService)
    graph = make_graph()
    preferences = cast(dict[str, object], SESSION_INPUT["preferences"])
    incomplete: dict[str, object] = dict(SESSION_INPUT)
    incomplete.update(
        {
            "target_directions": [],
            "preferences": {
                **preferences,
                "location": None,
                "employment_type": None,
            },
        }
    )

    paused = run_workflow(graph, "real-resume", input_data=incomplete)
    resumed = run_workflow(
        graph,
        "real-resume",
        answers={
            "target_directions": "后端开发",
            "preferences.location": "香港",
            "preferences.employment_type": "full-time",
        },
    )

    assert paused["outcome"] == "paused"
    assert resumed["outcome"] == "completed"
    assert resumed["state"]["recommendation"] is not None


def test_real_graph_rejects_invalid_input() -> None:
    result = run_workflow(make_graph(), "real-invalid", input_data={"description": 123})

    assert result["outcome"] == "failed"
    assert result["state"]["current_stage"] == "failed"
    assert result["state"]["errors"]
