"""Conversation, summary and evidence contracts owned by the application."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from jobscout.schemas.profile import UserProfile


class ConversationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    value: str | list[str]
    status: Literal["answered", "skipped"] = "answered"


class ConversationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str
    role: Literal["user", "assistant"]
    text: str
    responses: list[ConversationResponse] = Field(default_factory=list)
    question_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class QuestionOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str


class QuestionAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    value: str | list[str]


class SearchSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: UserProfile
    revision: int
    ready: bool = False
    confirmed: bool = False
    editable_fields: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    coverage_notice: str = "检索香港及中国内地受支持的招聘来源。"


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    excerpt: str
    source_url: str | None = None


class MatchingReason(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement: str
    level: Literal["strong", "partial", "related_experience", "not_evidenced"]
    explanation: str
    job_evidence: list[EvidenceReference] = Field(default_factory=list)
    profile_evidence: list[EvidenceReference] = Field(default_factory=list)
