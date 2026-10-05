import operator
from typing import Annotated, Any, Literal, NotRequired, TypedDict

from jobscout.schemas.conversation import ConversationMessage, SearchSummary
from jobscout.schemas.errors import WorkflowError
from jobscout.schemas.job import JobPosting, SourceDocument
from jobscout.schemas.notices import ApplicantNotice
from jobscout.schemas.profile import UserProfile
from jobscout.schemas.recommendation import RecommendationResult
from jobscout.schemas.search import ClarificationMessage, SearchRequest
from jobscout.services.job_retrieval.models import SourceOutcome

WorkflowStage = Literal[
    "ingest",
    "profile",
    "validate",
    "clarify",
    "confirm",
    "edit_conditions",
    "plan",
    "retrieve",
    "review",
    "normalize",
    "understand",
    "check_result_count",
    "present",
    "completed",
    "failed",
]


class AgentState(TypedDict):
    session_id: str
    input_data: NotRequired[dict[str, object]]
    profile: NotRequired[UserProfile | None]
    clarification_questions: NotRequired[list[ClarificationMessage]]
    search_requests: NotRequired[list[SearchRequest]]
    raw_jobs: NotRequired[list[dict[str, object]]]
    normalized_jobs: NotRequired[list[JobPosting]]
    recommendation: NotRequired[RecommendationResult | None]
    current_stage: NotRequired[WorkflowStage]
    errors: NotRequired[Annotated[list[WorkflowError], operator.add]]
    source_errors: NotRequired[Annotated[list[WorkflowError], operator.add]]
    warnings: NotRequired[Annotated[list[str], operator.add]]
    notices: NotRequired[Annotated[list[ApplicantNotice], operator.add]]
    revision: NotRequired[int]
    outcome: NotRequired[Literal["running", "paused", "completed", "failed"]]
    retryable: NotRequired[bool]
    mode: NotRequired[Literal["live", "replay"]]
    conversation: NotRequired[list[ConversationMessage]]
    search_summary: NotRequired[SearchSummary | None]
    source_outcomes: NotRequired[list[SourceOutcome]]
    profile_documents: NotRequired[list[SourceDocument]]
    required_attempts: NotRequired[dict[str, int]]
    optional_rounds: NotRequired[int]
    question_turn: NotRequired[int]
    suppressed_fields: NotRequired[list[str]]
    direct_edit_fields: NotRequired[list[str]]
    command: NotRequired[dict[str, object] | None]
    resume_payload: NotRequired[dict[str, object]]
    failed_resume_payload: NotRequired[dict[str, object] | None]
    applied_request_id: NotRequired[str]
    confirmed_profile: NotRequired[UserProfile | None]
    operation_deadline: NotRequired[float]
    retrieval_seconds: NotRequired[float]
    retrieval_round: NotRequired[int]
    analyzed_job_ids: NotRequired[list[str]]
    analysis_jobs: NotRequired[list[JobPosting]]
    assessment: NotRequired[RecommendationResult | None]
    jd_cache: NotRequired[dict[str, object]]
    run_id: NotRequired[str | None]
    progress_seq: NotRequired[int]
    progress: NotRequired[dict[str, Any]]
    stop_reason: NotRequired[str | None]
    model_usage: NotRequired[dict[str, int]]
    agent_error_code: NotRequired[str | None]
