from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from jobscout.schemas.conversation import ConversationMessage, QuestionAnswer, SearchSummary
from jobscout.schemas.errors import WorkflowError
from jobscout.schemas.profile import ProfilePreferences, UserProfile
from jobscout.schemas.recommendation import RecommendationResult
from jobscout.schemas.search import ClarificationMessage
from jobscout.services.job_retrieval.models import SourceOutcome


class ResumeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    text: str


class SessionInputPreferences(ProfilePreferences):
    pass


class SessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=128)
    description: str = ""
    resume: ResumeInput | None = None
    target_directions: list[str] = Field(default_factory=list)
    preferences: SessionInputPreferences = Field(default_factory=SessionInputPreferences)


class SessionResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=0)
    message: str = ""
    answers: list[QuestionAnswer] = Field(default_factory=list)
    skipped_question_ids: list[str] = Field(default_factory=list)
    action: Literal["answer", "confirm_search", "edit_conditions", "retry"] = "answer"
    profile_updates: dict[str, str | list[str] | bool | None] = Field(default_factory=dict)


class SessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    outcome: Literal["running", "paused", "completed", "failed"]
    current_stage: str = "ingest"
    revision: int = 0
    profile: UserProfile | None = None
    clarification_questions: list[ClarificationMessage] = Field(default_factory=list)
    conversation: list[ConversationMessage] = Field(default_factory=list)
    search_summary: SearchSummary | None = None
    source_outcomes: list[SourceOutcome] = Field(default_factory=list)
    recommendation: RecommendationResult | None = None
    errors: list[WorkflowError] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    retryable: bool = False
    mode: Literal["live", "replay"] = "live"
