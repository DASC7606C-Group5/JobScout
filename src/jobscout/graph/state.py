"""Shared state contract for one JobScout graph session."""

from typing import Literal, NotRequired, TypedDict

from jobscout.schemas.errors import WorkflowError
from jobscout.schemas.job import JobPosting
from jobscout.schemas.profile import UserProfile
from jobscout.schemas.recommendation import RecommendationResult
from jobscout.schemas.search import ClarificationMessage, SearchRequest

WorkflowStage = Literal[
    "ingest",
    "profile",
    "validate",
    "clarify",
    "search",
    "process_jobs",
    "recommend",
    "completed",
    "failed",
]


class AgentState(TypedDict):
    """Serializable data passed between nodes for one workflow session."""

    session_id: str
    input_data: NotRequired[dict[str, object]]
    profile: NotRequired[UserProfile | None]
    clarification_questions: NotRequired[list[ClarificationMessage]]
    search_requests: NotRequired[list[SearchRequest]]
    raw_jobs: NotRequired[list[dict[str, object]]]
    normalized_jobs: NotRequired[list[JobPosting]]
    recommendation: NotRequired[RecommendationResult | None]
    current_stage: NotRequired[WorkflowStage]
    errors: NotRequired[list[WorkflowError]]
    warnings: NotRequired[list[str]]
