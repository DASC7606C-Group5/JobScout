from datetime import UTC, datetime
from typing import TypedDict

from langgraph.types import interrupt

from jobscout.graph.state import AgentState
from jobscout.schemas.errors import WorkflowError
from jobscout.schemas.job import JobPosting
from jobscout.schemas.profile import ProfilePreferences, ProfileSource, UserProfile
from jobscout.schemas.recommendation import RecommendationItem, RecommendationResult
from jobscout.schemas.search import ClarificationMessage, ClarificationStatus


class MockNodeUpdate(TypedDict, total=False):
    profile: UserProfile
    raw_jobs: list[dict[str, object]]
    normalized_jobs: list[JobPosting]
    recommendation: RecommendationResult
    clarification_questions: list[ClarificationMessage]
    errors: list[WorkflowError]
    warnings: list[str]
    current_stage: str


MOCK_JOB = {
    "job_id": "job-1",
    "source": "mock",
    "source_url": "https://example.com/jobs/1",
    "title": "Data Analyst Intern",
    "company": "Example Co",
    "location": "Hong Kong",
    "target_direction": "data analyst",
    "fetched_at": datetime(2026, 9, 30, tzinfo=UTC),
}


def mock_profile_node(state: AgentState) -> MockNodeUpdate:
    if state.get("profile") is not None:
        return {"current_stage": "profile"}

    input_data = state.get("input_data", {})
    preferences_data = input_data.get("preferences", {})
    preferences_data = preferences_data if isinstance(preferences_data, dict) else {}
    resume_data = input_data.get("resume")
    resume_data = resume_data if isinstance(resume_data, dict) else {}
    description = input_data.get("description", "")
    directions_data = input_data.get("target_directions", [])
    directions = (
        [
            direction.strip()
            for direction in directions_data
            if isinstance(direction, str) and direction.strip()
        ]
        if isinstance(directions_data, list)
        else []
    )
    location = preferences_data.get("location")
    employment_type = preferences_data.get("employment_type")
    location_unrestricted = preferences_data.get("location_unrestricted") is True
    has_session_input = any(
        field in input_data
        for field in ("description", "resume", "target_directions", "preferences")
    )

    requested_fields = input_data.get("mock_missing_fields", [])
    missing_fields = (
        [field for field in requested_fields if isinstance(field, str)]
        if isinstance(requested_fields, list)
        else []
    )
    if has_session_input:
        if not directions:
            missing_fields.append("target_directions")
        if not location and not location_unrestricted:
            missing_fields.append("preferences.location")
        if not employment_type:
            missing_fields.append("preferences.employment_type")

    if not has_session_input:
        directions = ["data analyst"]
        location = "Hong Kong"
        employment_type = "internship"

    profile = UserProfile(
        profile_id="profile-1",
        source=ProfileSource(
            resume=bool(resume_data.get("text")),
            description=isinstance(description, str) and bool(description.strip()),
        ),
        target_directions=[] if "target_directions" in missing_fields else directions,
        preferences=ProfilePreferences(
            location=None if "preferences.location" in missing_fields else location,
            location_unrestricted=location_unrestricted,
            employment_type=(
                None if "preferences.employment_type" in missing_fields else employment_type
            ),
            salary_range=preferences_data.get("salary_range"),
            work_mode=preferences_data.get("work_mode"),
            industry=preferences_data.get("industry"),
        ),
        missing_required_fields=missing_fields,
    )
    return {
        "profile": profile,
        "current_stage": "profile",
    }


def mock_validation_node(state: AgentState) -> MockNodeUpdate:
    return {"current_stage": "validate"}


def mock_clarification_node(state: AgentState) -> MockNodeUpdate:
    profile = state.get("profile")
    if profile is None:
        questions = [
            ClarificationMessage(
                question="What kind of roles are you looking for?",
                field="target_directions",
                reason="A target direction is required to search for jobs.",
            )
        ]
    else:
        questions = [
            ClarificationMessage(
                question=f"Please provide {field}.",
                field=field,
                reason="This field is required to search for jobs.",
            )
            for field in profile.missing_required_fields
        ]
    if not state.get("clarification_questions"):
        return {"clarification_questions": questions, "current_stage": "clarify"}

    resumed = interrupt(
        {
            "questions": [
                question.model_dump(mode="json")
                for question in state.get("clarification_questions", [])
            ],
            "message": "Answer the pending clarification questions to continue.",
        }
    )
    answers = resumed.get("answers", {}) if isinstance(resumed, dict) else {}
    if profile is None or not isinstance(answers, dict):
        return {"current_stage": "clarify"}

    questions = list(state.get("clarification_questions", []))
    preferences = profile.preferences.model_copy()
    target_directions = list(profile.target_directions)
    answered_fields: set[str] = set()

    for field, answer in answers.items():
        if not isinstance(field, str) or not isinstance(answer, str) or not answer.strip():
            continue
        if field == "preferences.location":
            preferences.location = answer.strip()
        elif field == "preferences.employment_type":
            preferences.employment_type = answer.strip()
        elif field == "target_directions":
            target_directions = [answer.strip()]
        else:
            continue
        answered_fields.add(field)

    updated_profile = profile.model_copy(
        update={
            "preferences": preferences,
            "target_directions": target_directions,
            "missing_required_fields": [
                field for field in profile.missing_required_fields if field not in answered_fields
            ],
        }
    )
    updated_questions = [
        question.model_copy(
            update={
                "status": ClarificationStatus.ANSWERED,
                "answer": answers[question.field],
            }
        )
        if question.field in answered_fields
        else question
        for question in questions
    ]
    return {
        "profile": updated_profile,
        "clarification_questions": updated_questions,
        "current_stage": "clarify",
    }


def mock_completed_node(state: AgentState) -> MockNodeUpdate:
    update: MockNodeUpdate = {"current_stage": "completed"}
    if not state.get("raw_jobs") and not state.get("normalized_jobs"):
        update["warnings"] = ["No jobs were found."]
    return update


def mock_failed_node(state: AgentState) -> MockNodeUpdate:
    return {"current_stage": "failed"}


def mock_search_node(state: AgentState) -> MockNodeUpdate:
    input_data = state.get("input_data", {})
    if input_data.get("mock_no_jobs") is True:
        return {"raw_jobs": [], "current_stage": "search"}

    return {
        "raw_jobs": [MOCK_JOB.copy()],
        "current_stage": "search",
    }


def mock_processing_node(state: AgentState) -> MockNodeUpdate:
    raw_jobs = state.get("raw_jobs", [])
    normalized_jobs = [JobPosting.model_validate(raw_job) for raw_job in raw_jobs]
    return {
        "normalized_jobs": normalized_jobs,
        "current_stage": "process_jobs",
    }


def mock_recommendation_node(state: AgentState) -> MockNodeUpdate:
    jobs = state.get("normalized_jobs", [])
    recommendation = RecommendationResult(
        session_id=state["session_id"],
        generated_at=datetime.now(UTC),
        jobs=[RecommendationItem(job=job) for job in jobs[:5]],
    )
    return {
        "recommendation": recommendation,
        "current_stage": "recommend",
    }
