"""Tests for graph routing and clarification flow."""

from datetime import UTC, datetime
from typing import Any, cast

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from jobscout.graph.builder import build_mock_graph
from jobscout.graph.nodes.mock import (
    mock_processing_node,
    mock_profile_node,
    mock_recommendation_node,
    mock_search_node,
)
from jobscout.graph.routing import (
    route_after_clarification,
    route_after_processing,
    route_after_recommendation,
    route_after_search,
    route_after_validation,
)
from jobscout.graph.state import AgentState
from jobscout.schemas.errors import WorkflowError
from jobscout.schemas.job import JobPosting
from jobscout.schemas.profile import ProfilePreferences, ProfileSource, UserProfile
from jobscout.schemas.recommendation import RecommendationResult
from jobscout.schemas.search import ClarificationMessage, ClarificationStatus


def make_state(**updates: object) -> AgentState:
    state: dict[str, object] = {"session_id": "session-1"}
    state.update(updates)
    return cast(AgentState, state)


def make_complete_profile() -> UserProfile:
    return UserProfile(
        profile_id="profile-1",
        source=ProfileSource(description=True),
        target_directions=["data analyst"],
        preferences=ProfilePreferences(
            location="Hong Kong",
            employment_type="internship",
        ),
    )


def make_job() -> JobPosting:
    return JobPosting(
        job_id="job-1",
        source="mock",
        source_url="https://example.com/jobs/1",
        title="Data Analyst Intern",
        company="Example Co",
        location="Hong Kong",
        target_direction="data analyst",
        fetched_at=datetime(2026, 9, 30, tzinfo=UTC),
    )


def test_complete_profile_routes_to_search() -> None:
    state = make_state(profile=make_complete_profile())

    assert route_after_validation(state) == "search"


def test_missing_profile_routes_to_clarification() -> None:
    state = make_state()

    assert route_after_validation(state) == "clarify"


def test_missing_required_fields_route_to_clarification() -> None:
    profile = make_complete_profile()
    profile.missing_required_fields = ["preferences.employment_type"]

    assert route_after_validation(make_state(profile=profile)) == "clarify"


def test_profile_conflicts_route_to_clarification() -> None:
    profile = make_complete_profile()
    profile.conflicts = ["skills"]

    assert route_after_validation(make_state(profile=profile)) == "clarify"


def test_workflow_errors_route_to_failure() -> None:
    error = WorkflowError(
        code="profile_error",
        message="Profile extraction failed.",
        stage="profile",
    )

    assert route_after_validation(make_state(errors=[error])) == "failed"


def test_pending_required_question_stays_in_clarification() -> None:
    question = ClarificationMessage(
        question="Which location do you prefer?",
        field="preferences.location",
        reason="Location is required.",
    )

    assert route_after_clarification(make_state(clarification_questions=[question])) == "clarify"


def test_answered_questions_route_to_validation() -> None:
    question = ClarificationMessage(
        question="Which location do you prefer?",
        field="preferences.location",
        reason="Location is required.",
        status=ClarificationStatus.ANSWERED,
        answer="Hong Kong",
    )

    assert route_after_clarification(make_state(clarification_questions=[question])) == "validate"


def test_search_results_route_to_processing() -> None:
    assert route_after_search(make_state(raw_jobs=[{"job_id": "job-1"}])) == "process_jobs"


def test_empty_search_results_route_to_completed() -> None:
    assert route_after_search(make_state(raw_jobs=[])) == "completed"


def test_processed_jobs_route_to_recommendation() -> None:
    assert route_after_processing(make_state(normalized_jobs=[make_job()])) == "recommend"


def test_empty_processed_jobs_route_to_completed() -> None:
    assert route_after_processing(make_state(normalized_jobs=[])) == "completed"


def test_recommendation_routes_to_completed() -> None:
    recommendation = RecommendationResult(
        session_id="session-1",
        generated_at=datetime(2026, 9, 30, tzinfo=UTC),
        jobs=[],
    )

    assert route_after_recommendation(make_state(recommendation=recommendation)) == "completed"


def test_missing_recommendation_routes_to_failure() -> None:
    assert route_after_recommendation(make_state()) == "failed"


def test_mock_profile_node_returns_profile() -> None:
    result = mock_profile_node(make_state())

    assert result["current_stage"] == "profile"
    assert isinstance(result["profile"], UserProfile)


def test_mock_search_node_returns_raw_jobs() -> None:
    result = mock_search_node(make_state())

    assert result["current_stage"] == "search"
    assert len(result["raw_jobs"]) == 1


def test_mock_processing_node_returns_normalized_jobs() -> None:
    result = mock_processing_node(make_state(raw_jobs=[make_job().model_dump()]))

    assert result["current_stage"] == "process_jobs"
    assert result["normalized_jobs"] == [make_job()]


def test_mock_recommendation_node_returns_recommendation() -> None:
    result = mock_recommendation_node(make_state(normalized_jobs=[make_job()]))
    recommendation = result["recommendation"]

    assert result["current_stage"] == "recommend"
    assert isinstance(recommendation, RecommendationResult)
    assert len(recommendation.jobs) == 1


def test_mock_graph_runs_happy_path() -> None:
    result = build_mock_graph().invoke(make_state())

    assert result["current_stage"] == "completed"
    assert len(result["raw_jobs"]) == 1
    assert len(result["normalized_jobs"]) == 1
    assert isinstance(result["recommendation"], RecommendationResult)


def test_mock_graph_completes_with_warning_when_search_is_empty() -> None:
    result = build_mock_graph().invoke(make_state(input_data={"mock_no_jobs": True}))

    assert result["current_stage"] == "completed"
    assert result["raw_jobs"] == []
    assert "No jobs were found." in result["warnings"]


def test_mock_graph_routes_errors_to_failed_and_preserves_them() -> None:
    error = WorkflowError(
        code="profile_error",
        message="Profile extraction failed.",
        stage="profile",
    )

    result = build_mock_graph().invoke(make_state(errors=[error]))

    assert result["current_stage"] == "failed"
    assert result["errors"] == [error]


def test_mock_graph_pauses_for_missing_profile_fields() -> None:
    graph = build_mock_graph(checkpointer=InMemorySaver())
    config: Any = {"configurable": {"thread_id": "session-1"}}
    result = graph.invoke(
        make_state(input_data={"mock_missing_fields": ["preferences.location"]}), config
    )

    assert result["current_stage"] == "clarify"
    assert result["clarification_questions"][0].field == "preferences.location"
    assert result.get("raw_jobs") is None
    snapshot = graph.get_state(config)
    assert snapshot.next == ("clarify",)

    resumed = graph.invoke(
        Command(resume={"answers": {"preferences.location": "Hong Kong"}}), config
    )

    assert resumed["current_stage"] == "completed"
    assert resumed["profile"].preferences.location == "Hong Kong"
    assert resumed["clarification_questions"][0].status == ClarificationStatus.ANSWERED
    assert resumed["raw_jobs"]


def test_mock_graph_resumes_after_clarification_answer() -> None:
    profile = make_complete_profile()
    question = ClarificationMessage(
        question="Which location do you prefer?",
        field="preferences.location",
        reason="Location is required.",
        status=ClarificationStatus.ANSWERED,
        answer="Hong Kong",
    )
    result = build_mock_graph().invoke(
        make_state(profile=profile, clarification_questions=[question])
    )

    assert result["current_stage"] == "completed"
    assert len(result["raw_jobs"]) == 1
