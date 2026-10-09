"""Shared history, independent favorites and unnormalized editable form drafts."""

from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field

from jobscout.schemas.recommendation import RecommendationItem
from jobscout.schemas.session import ResumeInput
from jobscout.schemas.wire import WireModel


class SessionHistoryItem(WireModel):
    session_id: str
    title: str
    location: str
    outcome: Literal["queued", "running", "paused", "completed", "failed", "cancelled"]
    current_stage: str
    revision: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime
    retryable: bool
    mode: Literal["live", "replay"]


class SessionHistoryResponse(WireModel):
    items: list[SessionHistoryItem]
    next_cursor: str | None


class DraftWriteRequest(WireModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=0)
    data: dict[str, Any]


class DraftResponse(WireModel):
    data: dict[str, Any]
    revision: int = Field(ge=0)
    updated_at: datetime | None


class RawPreferences(WireModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    location: str | None
    location_unrestricted: bool
    employment_type: str | None
    employment_type_unrestricted: bool
    salary_range: str | None
    work_mode: str | None
    industry: str | None


class ProfileDraft(WireModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    description: str
    resume: ResumeInput | None
    resume_consent: bool = False
    directions: str
    preferences: RawPreferences
    search_options: DraftSearchOptions = Field(default_factory=lambda: DraftSearchOptions())


class DraftSearchOptions(WireModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    result_count: int = 10


class ClarificationDraft(WireModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    values: dict[str, str | list[str]]
    skipped: list[str]
    message: str


class SummaryFields(WireModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    education: str
    skills: str
    internships: str
    projects: str
    target_directions: str
    location: str = Field(alias="preferences.location")
    location_unrestricted: bool = Field(alias="preferences.location_unrestricted")
    employment_type: str = Field(alias="preferences.employment_type")
    employment_type_unrestricted: bool = Field(alias="preferences.employment_type_unrestricted")
    salary_range: str = Field(alias="preferences.salary_range")
    work_mode: str = Field(alias="preferences.work_mode")
    industry: str = Field(alias="preferences.industry")
    result_count: int = Field(default=10, alias="search_options.result_count")


class SummaryDraft(WireModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    fields: SummaryFields
    message: str


class SaveJobRequest(WireModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    expected_revision: int = Field(ge=0)


class SavedJobsResponse(WireModel):
    items: list[RecommendationItem]
