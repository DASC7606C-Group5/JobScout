from collections.abc import ItemsView, ValuesView
from typing import Literal

from pydantic import ConfigDict, Field, field_serializer

from jobscout.schemas.conversation import ConversationMessage, QuestionAnswer, SearchSummary
from jobscout.schemas.errors import ApplicantError
from jobscout.schemas.execution import SearchProgress, StopReason
from jobscout.schemas.feedback import HiddenJobReason, JobFeedback, ResultPreferences
from jobscout.schemas.notices import ApplicantNotice
from jobscout.schemas.profile import RawProfilePreferences, SearchOptions, UserProfile
from jobscout.schemas.recommendation import RecommendationResult
from jobscout.schemas.search import ClarificationMessage
from jobscout.schemas.wire import WireModel
from jobscout.services.job_retrieval.models import SourceOutcome


class ResumeInput(WireModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    text: str


class SessionCreateRequest(WireModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=128)
    description: str = ""
    resume: ResumeInput | None = None
    resume_consent: bool = False
    target_directions: list[str] = Field(default_factory=list)
    preferences: RawProfilePreferences = Field(default_factory=RawProfilePreferences)
    search_options: SearchOptions = Field(default_factory=SearchOptions)


type PatchValue = str | list[str] | bool | None


class ProfilePatch(WireModel):
    """Only supplied fields change; null clears text and an empty list clears a list."""

    model_config = ConfigDict(extra="forbid", strict=True, serialize_by_alias=True)

    education: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    internships: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    target_directions: list[str] = Field(default_factory=list)
    location: str | None = Field(default=None, alias="preferences.location")
    location_unrestricted: bool = Field(default=False, alias="preferences.location_unrestricted")
    employment_type: str | None = Field(default=None, alias="preferences.employment_type")
    employment_type_unrestricted: bool = Field(
        default=False, alias="preferences.employment_type_unrestricted"
    )
    salary_range: str | None = Field(default=None, alias="preferences.salary_range")
    work_mode: str | None = Field(default=None, alias="preferences.work_mode")
    industry: str | None = Field(default=None, alias="preferences.industry")

    def supplied(self) -> dict[str, PatchValue]:
        return self.model_dump(by_alias=True, exclude_unset=True)

    def items(self) -> ItemsView[str, PatchValue]:
        return self.supplied().items()

    def values(self) -> ValuesView[PatchValue]:
        return self.supplied().values()

    def __bool__(self) -> bool:
        return bool(self.model_fields_set)


class SessionResumeRequest(WireModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=0)
    message: str = ""
    answers: list[QuestionAnswer] = Field(default_factory=list)
    skipped_question_ids: list[str] = Field(default_factory=list)
    action: Literal["answer", "confirm_search", "edit_conditions", "retry"] = "answer"
    profile_updates: ProfilePatch = Field(default_factory=ProfilePatch)
    search_options: SearchOptions | None = None

    @field_serializer("profile_updates")
    def serialize_updates(self, value: ProfilePatch) -> dict[str, PatchValue]:
        return value.supplied()


class SessionStopRequest(WireModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=0)
    run_id: str = Field(min_length=1, max_length=128)


class SessionResponse(WireModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    operation_kind: Literal["initial_search", "follow_up"] = "initial_search"
    job_feedback: list[JobFeedback] = Field(default_factory=list)
    hidden_job_ids: list[str] = Field(default_factory=list)
    hidden_job_reasons: list[HiddenJobReason] = Field(default_factory=list)
    result_preferences: ResultPreferences = Field(default_factory=ResultPreferences)
    result_order: list[str] = Field(default_factory=list)
    outcome: Literal["running", "paused", "completed", "failed"]
    current_stage: str = "ingest"
    revision: int = Field(default=0, ge=0)
    profile: UserProfile | None = None
    clarification_questions: list[ClarificationMessage] = Field(default_factory=list)
    conversation: list[ConversationMessage] = Field(default_factory=list)
    search_summary: SearchSummary | None = None
    source_outcomes: list[SourceOutcome] = Field(default_factory=list)
    recommendation: RecommendationResult | None = None
    errors: list[ApplicantError] = Field(default_factory=list)
    notices: list[ApplicantNotice] = Field(default_factory=list)
    retryable: bool = False
    mode: Literal["live", "replay"] = "live"
    run_id: str | None = None
    progress: SearchProgress = Field(default_factory=SearchProgress)
    stop_reason: StopReason | None = None
