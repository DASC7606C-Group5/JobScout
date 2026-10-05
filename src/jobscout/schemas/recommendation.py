"""Recommendation contracts consumed by the frontend."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from jobscout.schemas.conversation import MatchingReason
from jobscout.schemas.job import JobPosting
from jobscout.schemas.notices import ApplicantNotice


class RecommendationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job: JobPosting
    preparation_suggestions: list[str] = Field(default_factory=list)
    matching_reasons: list[MatchingReason] = Field(default_factory=list)
    notices: list[ApplicantNotice] = Field(default_factory=list)
    analysis_status: Literal["complete", "partial", "unavailable"] = "complete"


class RecommendationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    generated_at: datetime
    jobs: list[RecommendationItem] = Field(default_factory=list, max_length=5)
    notices: list[ApplicantNotice] = Field(default_factory=list)
    introduction: str = ""
