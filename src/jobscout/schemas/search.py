"""Search and clarification contracts exchanged by workflow and API layers."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from jobscout.schemas.conversation import QuestionOption


class ClarificationStatus(StrEnum):
    PENDING = "pending"
    ANSWERED = "answered"
    SKIPPED = "skipped"


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_direction: str
    keywords: list[str] = Field(default_factory=list)
    location: str | None = None
    location_unrestricted: bool = False
    employment_type: str = ""
    employment_type_unrestricted: bool = False
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
    question_id: str = ""
    control_type: Literal["single_choice", "multiple_choice", "text"] = "text"
    options: list[QuestionOption] = Field(default_factory=list)
