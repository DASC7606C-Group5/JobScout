"""Public progress facts for one confirmed search execution."""

from typing import Literal

from pydantic import ConfigDict, Field

from jobscout.schemas.job_status import ExclusionReason, JobStatus, ReviewIssue
from jobscout.schemas.recommendation import RecommendationFit
from jobscout.schemas.wire import WireModel

StopReason = Literal[
    "results_ready",
    "target_reached",
    "source_exhausted",
    "budget_exhausted",
    "user_stopped",
    "error",
]


class SearchEvent(WireModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    action: str
    message: str
    source: str | None = None


class SearchActivity(WireModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    job_id: str
    title: str
    company: str
    location: str
    status: JobStatus
    review_issue: ReviewIssue | None = None
    exclusion_reasons: list[ExclusionReason] = Field(default_factory=list)
    unknown_conditions: list[str] = Field(default_factory=list)
    recommendation_fit: RecommendationFit = "unknown"


class SearchProgress(WireModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(default=0, ge=0)
    discovered_count: int = Field(default=0, ge=0)
    analyzed_count: int = Field(default=0, ge=0)
    matched_count: int = Field(default=0, ge=0)
    pending_count: int = Field(default=0, ge=0)
    elapsed_seconds: float = Field(default=0, ge=0)
    retrieval_stopped: bool = False
    events: list[SearchEvent] = Field(default_factory=list)
    activity: list[SearchActivity] = Field(default_factory=list, max_length=250)
