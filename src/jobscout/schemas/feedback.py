"""Session-scoped reactions, exclusions and result conversation requests."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from jobscout.schemas.conversation import QuestionAnswer
from jobscout.schemas.wire import WireModel


class FeedbackModel(WireModel):
    model_config = ConfigDict(extra="forbid")


class JobFeedback(FeedbackModel):
    job_id: str
    reaction: Literal["interested", "not_interested"]
    reason: str | None = None
    updated_at: datetime


class ResultExclusion(FeedbackModel):
    exclusion_id: str
    description: str
    user_message_id: str


class ResultPreferences(FeedbackModel):
    preferred_features: list[str] = Field(default_factory=list)
    exclusions: list[ResultExclusion] = Field(default_factory=list)


class HiddenJobReason(FeedbackModel):
    job_id: str
    kind: Literal["not_interested", "excluded"]
    exclusion_id: str | None = None


class ResultRequest(FeedbackModel):
    request_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=0)


class SessionFeedbackRequest(ResultRequest):
    job_id: str = Field(min_length=1)
    reaction: Literal["interested", "not_interested"] | None


class FollowUpMessageRequest(ResultRequest):
    action: Literal["message"]
    job_id: str | None = None
    message: str


class FindSimilarRequest(ResultRequest):
    action: Literal["find_similar"]
    job_id: str
    message: str = ""


class FollowUpAnswerRequest(ResultRequest):
    action: Literal["answer"]
    answers: list[QuestionAnswer] = Field(default_factory=list)
    skipped_question_ids: list[str] = Field(default_factory=list)
    message: str = ""


type SessionFollowUpRequest = Annotated[
    FollowUpMessageRequest | FindSimilarRequest | FollowUpAnswerRequest,
    Field(discriminator="action"),
]
