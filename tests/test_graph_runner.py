"""Tests for the graph workflow execution entry point."""

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from jobscout.graph.builder import build_mock_graph
from jobscout.graph.runner import run_workflow
from jobscout.schemas.search import ClarificationStatus


def make_graph() -> Any:
    return build_mock_graph(checkpointer=InMemorySaver())


def test_runner_completes_a_workflow() -> None:
    result = run_workflow(make_graph(), "session-1")

    assert result["outcome"] == "completed"
    assert result["state"]["current_stage"] == "completed"


def test_runner_returns_paused_for_missing_information() -> None:
    result = run_workflow(
        make_graph(),
        "session-1",
        input_data={"mock_missing_fields": ["preferences.location"]},
    )

    assert result["outcome"] == "paused"
    assert result["state"]["current_stage"] == "clarify"


def test_runner_resumes_a_paused_workflow() -> None:
    graph = make_graph()
    paused = run_workflow(
        graph,
        "session-1",
        input_data={"mock_missing_fields": ["preferences.location"]},
    )

    resumed = run_workflow(
        graph,
        "session-1",
        answers={"preferences.location": "Hong Kong"},
    )

    assert paused["outcome"] == "paused"
    assert resumed["outcome"] == "completed"
    assert resumed["state"]["clarification_questions"][0].status == (ClarificationStatus.ANSWERED)


def test_runner_keeps_sessions_isolated() -> None:
    graph = make_graph()
    paused = run_workflow(
        graph,
        "session-1",
        input_data={"mock_missing_fields": ["preferences.location"]},
    )
    completed = run_workflow(graph, "session-2")

    assert paused["outcome"] == "paused"
    assert completed["outcome"] == "completed"


def test_runner_returns_failed_when_resuming_without_checkpoint() -> None:
    result = run_workflow(
        make_graph(),
        "session-1",
        answers={"preferences.location": "Hong Kong"},
    )

    assert result["outcome"] == "failed"
    assert result["state"]["current_stage"] == "failed"
    assert result["state"]["errors"][0].code == "workflow_execution_error"


def test_runner_pauses_again_for_an_invalid_answer() -> None:
    graph = make_graph()
    result = run_workflow(
        graph,
        "session-1",
        input_data={"mock_missing_fields": ["preferences.location"]},
    )

    resumed = run_workflow(graph, "session-1", answers={"unknown": "value"})

    assert result["outcome"] == "paused"
    assert resumed["outcome"] == "paused"
    assert resumed["state"]["clarification_questions"][0].status == (ClarificationStatus.PENDING)
