"""Search and clarification contracts exchanged by workflow and API layers."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ClarificationStatus(StrEnum):
    PENDING = "pending"
    ANSWERED = "answered"


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_direction: str
    keywords: list[str] = Field(default_factory=list)
    location: str | None = None
    location_unrestricted: bool = False
    employment_type: str
    salary_range: str | None = None
    work_mode: str | None = None
    sources: list[str] = Field(default_factory=list)


class ClarificationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    field: str
    reason: str
    required: bool = True
    status: ClarificationStatus = ClarificationStatus.PENDING
    answer: str | None = None
