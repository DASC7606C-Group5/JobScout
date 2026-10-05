"""Shared history, independent favorites and unnormalized editable form drafts."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from jobscout.schemas.recommendation import RecommendationItem
from jobscout.schemas.session import ResumeInput


class SessionHistoryItem(BaseModel):
    session_id: str
    title: str
    location: str
    outcome: Literal["running", "paused", "completed", "failed"]
    current_stage: str
    revision: int
    created_at: datetime
    updated_at: datetime
    retryable: bool
    mode: Literal["live", "replay"]


class SessionHistoryResponse(BaseModel):
    items: list[SessionHistoryItem]
    next_cursor: str | None


class DraftWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=0)
    data: dict[str, Any]


class DraftResponse(BaseModel):
    data: dict[str, Any]
    revision: int
    updated_at: datetime | None


class RawPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    location: str | None
    location_unrestricted: bool
    employment_type: str | None
    employment_type_unrestricted: bool
    salary_range: str | None
    work_mode: str | None
    industry: str | None


class ProfileDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    description: str
    resume: ResumeInput | None
    directions: str
    preferences: RawPreferences
    search_options: DraftSearchOptions = Field(default_factory=lambda: DraftSearchOptions())


class DraftSearchOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    result_count: int = 10


class ClarificationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    values: dict[str, str | list[str]]
    skipped: list[str]
    message: str


class SummaryFields(BaseModel):
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


class SummaryDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    fields: SummaryFields
    message: str


class SaveJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    expected_revision: int = Field(ge=0)


class SavedJobsResponse(BaseModel):
    items: list[RecommendationItem]
