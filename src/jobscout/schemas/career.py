"""Current background, task feedback and source-independent application contracts."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from jobscout.schemas.job import SourceDocument
from jobscout.schemas.profile import ProfilePreferences, UserProfile
from jobscout.schemas.recommendation import RecommendationItem
from jobscout.schemas.session import ResumeInput

Interest = Literal["neutral", "interested", "not_interested"]
FeedbackScope = Literal["job", "task"]
ApplicationStage = Literal["not_applied", "applied", "interview", "closed"]


class Background(BaseModel):
    model_config = ConfigDict(extra="forbid")
    education: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    internships: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)


class ProfileWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    description: str = ""
    resume: ResumeInput | None = None
    background: Background = Field(default_factory=Background)
    documents: list[SourceDocument] = Field(default_factory=list)


class PersonalProfile(ProfileWrite):
    revision: int = 0
    updated_at: datetime | None = None


class FeedbackWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interest: Interest = "neutral"
    reason: str = Field(default="", max_length=10000)
    scope: FeedbackScope = "job"


class TaskJobFeedback(FeedbackWrite):
    session_id: str
    job_id: str
    item: RecommendationItem
    updated_at: datetime


class ApplicationWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage: ApplicationStage = "not_applied"
    note: str = Field(default="", max_length=10000)
    session_id: str | None = None


class ApplicationTransition(BaseModel):
    stage: ApplicationStage
    note: str
    changed_at: datetime


class JobApplication(BaseModel):
    job_id: str
    stage: ApplicationStage
    note: str
    item: RecommendationItem
    created_at: datetime
    updated_at: datetime
    history: list[ApplicationTransition]


class TaskMetadata(BaseModel):
    session_id: str
    title: str
    profile_revision: int | None = None
    preferences: ProfilePreferences
    target_directions: list[str]


def adopt_background(profile: UserProfile, current: PersonalProfile) -> UserProfile:
    """Replace background only; retain this task's conditions and directions."""
    return profile.model_copy(update=current.background.model_dump(), deep=True)
