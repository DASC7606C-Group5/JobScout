from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from jobscout.schemas.errors import WorkflowError
from jobscout.schemas.profile import UserProfile
from jobscout.schemas.recommendation import RecommendationResult
from jobscout.schemas.search import ClarificationMessage


class ResumeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    text: str


class SessionInputPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: str | None
    location_unrestricted: bool
    employment_type: str | None
    salary_range: str | None
    work_mode: str | None
    industry: str | None


class SessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    resume: ResumeInput | None
    target_directions: list[str]
    preferences: SessionInputPreferences


class SessionResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answers: dict[str, str]


class SessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    outcome: Literal["paused", "completed", "failed"]
    profile: UserProfile | None = None
    clarification_questions: list[ClarificationMessage] = Field(default_factory=list)
    recommendation: RecommendationResult | None = None
    errors: list[WorkflowError] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
