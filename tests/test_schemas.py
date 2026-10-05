"""Tests for shared Pydantic schema contracts."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from jobscout.schemas.conversation import QuestionAnswer, SearchSummary
from jobscout.schemas.errors import WorkflowError
from jobscout.schemas.job import FreshnessStatus, JobPosting
from jobscout.schemas.profile import ProfilePreferences, UserProfile
from jobscout.schemas.recommendation import RecommendationItem, RecommendationResult
from jobscout.schemas.search import ClarificationMessage, ClarificationStatus, SearchRequest


def make_job(job_id: str = "job-1") -> JobPosting:
    return JobPosting(
        job_id=job_id,
        source="mock",
        source_url="https://example.com/jobs/1",
        title="Data Analyst Intern",
        company="Example Co",
        location="Hong Kong",
        target_direction="data analyst",
        fetched_at=datetime(2026, 9, 30, tzinfo=UTC),
    )


def test_user_profile_constructs_with_nested_defaults() -> None:
    profile = UserProfile(profile_id="profile-1")

    assert profile.source.resume is False
    assert profile.preferences.location is None
    assert profile.target_directions == []


def test_profile_preferences_support_explicit_unrestricted_location() -> None:
    preferences = ProfilePreferences(location_unrestricted=True)

    assert preferences.location is None
    assert preferences.location_unrestricted is True


def test_explicit_unrestricted_type_is_distinct_from_missing() -> None:
    missing = ProfilePreferences()
    unrestricted = ProfilePreferences(employment_type_unrestricted=True)
    assert missing.employment_type is unrestricted.employment_type is None
    assert not missing.employment_type_unrestricted
    assert unrestricted.employment_type_unrestricted
    request = SearchRequest(target_direction="data analyst", employment_type_unrestricted=True)
    assert request.employment_type == ""
    assert request.employment_type_unrestricted


def test_conversation_contract_carries_typed_answers_and_summary_revision() -> None:
    answer = QuestionAnswer(question_id="q-1", value=["option-a", "option-b"])
    assert answer.model_dump()["value"] == ["option-a", "option-b"]
    summary = SearchSummary(profile=UserProfile(profile_id="p"), revision=2)
    assert summary.revision == 2
    assert not summary.confirmed
    assert not summary.ready


def test_search_request_constructs_with_optional_filters() -> None:
    request = SearchRequest(
        target_direction="data analyst",
        keywords=["Python", "SQL"],
        location_unrestricted=True,
        employment_type="internship",
    )

    assert request.location is None
    assert request.sources == []


def test_clarification_message_uses_pending_by_default() -> None:
    message = ClarificationMessage(
        question="Which employment type do you prefer?",
        field="preferences.employment_type",
        reason="Employment type is required before searching.",
    )

    assert message.status is ClarificationStatus.PENDING
    assert message.answer is None


def test_clarification_message_accepts_answered_status() -> None:
    message = ClarificationMessage(
        question="Which location do you prefer?",
        field="preferences.location",
        reason="Location is missing.",
        status=ClarificationStatus.ANSWERED,
        answer="Hong Kong",
    )

    assert message.status is ClarificationStatus.ANSWERED
    assert message.answer == "Hong Kong"


def test_job_posting_uses_unknown_freshness_by_default() -> None:
    job = make_job()

    assert job.freshness_status is FreshnessStatus.UNKNOWN
    assert job.responsibilities == []
    assert job.required_skills == []


def test_job_posting_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        JobPosting.model_validate({**make_job().model_dump(), "unexpected": "value"})


def test_recommendation_result_limits_jobs_to_five() -> None:
    items = [RecommendationItem(job=make_job(f"job-{index}")) for index in range(6)]

    with pytest.raises(ValidationError):
        RecommendationResult(
            session_id="session-1",
            generated_at=datetime(2026, 9, 30, tzinfo=UTC),
            jobs=items,
        )


def test_workflow_error_accepts_structured_details() -> None:
    error = WorkflowError(
        code="missing_field",
        message="A required field is missing.",
        stage="validation",
        details={"field": "employment_type", "required": True},
    )

    assert error.details == {"field": "employment_type", "required": True}


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (SearchRequest, {}),
        (JobPosting, {"job_id": "job-1"}),
        (WorkflowError, {"code": "error"}),
    ],
)
def test_required_fields_are_enforced(model: type[object], payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "model",
    [UserProfile, SearchRequest, JobPosting, RecommendationResult, WorkflowError],
)
def test_shared_models_reject_extra_fields(model: type[object]) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({"unexpected": "value"})  # type: ignore[attr-defined]
