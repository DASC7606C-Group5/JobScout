"""Public job review reasons. Never include provider messages or model output."""

from typing import Literal

from pydantic import ConfigDict

from jobscout.schemas.wire import WireModel

JobStatus = Literal[
    "found",
    "queued",
    "reviewing",
    "reviewed",
    "summary_reviewed",
    "not_reviewed",
    "partial",
    "timeout",
    "unavailable",
    "invalid",
    "insufficient",
    "failed",
    "excluded",
    "unverified",
    "expired",
    "duplicate",
    "not_shortlisted",
]
ExclusionReason = Literal["role", "location", "employment_type", "expired", "duplicate"]


class ReviewIssue(WireModel):
    model_config = ConfigDict(extra="forbid")

    code: Literal[
        "timeout",
        "service_unavailable",
        "invalid_output",
        "unverifiable_claims",
        "insufficient_job_information",
        "incomplete_review",
        "failed",
        "stopped",
        "search_ended",
    ]
    stage: Literal["jd_analysis", "matching"] | None = None


def issue_status(issue: ReviewIssue | None) -> JobStatus:
    if issue is None:
        return "failed"
    match issue.code:
        case "timeout":
            return "timeout"
        case "service_unavailable":
            return "unavailable"
        case "invalid_output" | "unverifiable_claims":
            return "invalid"
        case "insufficient_job_information":
            return "insufficient"
        case _:
            return "failed"
