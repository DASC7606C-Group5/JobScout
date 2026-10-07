"""Recommended jobs and their explanations returned to the frontend."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from jobscout.schemas.conversation import MatchingReason
from jobscout.schemas.job import JobPosting
from jobscout.schemas.job_status import JobStatus, ReviewIssue, issue_status
from jobscout.schemas.matching import MatchScore
from jobscout.schemas.notices import ApplicantNotice

RecommendationFit = Literal["recommended", "possible", "unlikely", "unknown"]


class RecommendationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job: JobPosting
    preparation_suggestions: list[str] = Field(default_factory=list)
    matching_reasons: list[MatchingReason] = Field(default_factory=list)
    notices: list[ApplicantNotice] = Field(default_factory=list)
    analysis_status: Literal["complete", "partial", "unavailable"] = "complete"
    review_status: Literal["queued", "reviewing", "reviewed", "not_reviewed"] = "reviewed"
    verification_status: Literal["confirmed", "pending", "unknown"] = "unknown"
    unknown_conditions: list[str] = Field(default_factory=list)
    review_issue: ReviewIssue | None = None
    recommendation_fit: RecommendationFit = "unknown"
    recommendation_reason: str = ""
    match_score: MatchScore | None = None

    def display_status(self, *, active: bool) -> JobStatus:
        if self.job.freshness_status == "expired":
            return "expired"
        if active and self.review_status in {"queued", "reviewing"}:
            return "queued" if self.review_status == "queued" else "reviewing"
        if self.review_status != "reviewed":
            if self.review_issue and self.review_issue.code not in {"stopped", "search_ended"}:
                return issue_status(self.review_issue)
            return "not_reviewed"
        if self.analysis_status == "unavailable":
            return issue_status(self.review_issue)
        if self.analysis_status == "partial":
            if not self.job.has_full_description() and self.review_issue is None:
                return "summary_reviewed"
            return "partial"
        if self.verification_status != "confirmed":
            return "unverified"
        return "reviewed"


class RecommendationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    generated_at: datetime
    jobs: list[RecommendationItem] = Field(default_factory=list, max_length=20)
    pending_jobs: list[RecommendationItem] = Field(default_factory=list, max_length=20)
    notices: list[ApplicantNotice] = Field(default_factory=list)
    introduction: str = ""
