"""Recommendation contracts consumed by the frontend."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from jobscout.schemas.conversation import MatchingReason
from jobscout.schemas.job import JobPosting


class RecommendationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job: JobPosting
    missing_skills: list[str] = Field(default_factory=list)
    preparation_suggestions: list[str] = Field(default_factory=list)
    matching_reasons: list[MatchingReason] = Field(default_factory=list)
    uncertainty_notices: list[str] = Field(default_factory=list)


class RecommendationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    generated_at: datetime
    jobs: list[RecommendationItem] = Field(default_factory=list, max_length=5)
    warnings: list[str] = Field(default_factory=list)
    introduction: str = ""
