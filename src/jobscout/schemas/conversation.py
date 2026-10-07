"""Messages, search summaries and source quotes returned by the application."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import ConfigDict, Field

from jobscout.schemas.profile import UserProfile
from jobscout.schemas.wire import WireModel


class ConversationResponse(WireModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    value: str | list[str]
    status: Literal["answered", "skipped"] = "answered"


class ConversationMessage(WireModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str
    role: Literal["user", "assistant"]
    text: str
    responses: list[ConversationResponse] = Field(default_factory=list)
    question_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class QuestionOption(WireModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str


class QuestionAnswer(WireModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    value: str | list[str]


class SearchSummary(WireModel):
    model_config = ConfigDict(extra="forbid")

    profile: UserProfile
    revision: int
    ready: bool = False
    confirmed: bool = False
    editable_fields: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    search_limitations: str = ""


class SourceQuoteReference(WireModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    excerpt: str
    source_url: str | None = None


class MatchingReason(WireModel):
    model_config = ConfigDict(extra="forbid")

    requirement: str
    level: Literal["strong", "partial", "related_experience", "not_documented"]
    explanation: str
    job_source_quotes: list[SourceQuoteReference] = Field(default_factory=list)
    profile_source_quotes: list[SourceQuoteReference] = Field(default_factory=list)
