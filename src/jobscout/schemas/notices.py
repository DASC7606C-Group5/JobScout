"""Applicant notices carry stable meaning independently of their display copy."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

NoticeCode = Literal[
    "source_unavailable",
    "source_partial",
    "coverage_limited",
    "listing_incomplete",
    "listing_status_unverified",
    "preference_unverified",
    "analysis_partial",
    "analysis_unavailable",
]


class ApplicantNotice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: NoticeCode
    scope: Literal["session", "source", "job"]
    message: str
    action: Literal["retry", "edit_conditions", "open_listing"] | None = None
    job_id: str | None = None
    source: str | None = None
    preference: str | None = None
