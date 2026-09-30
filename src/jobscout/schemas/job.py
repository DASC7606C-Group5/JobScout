"""Normalized job posting contract shared across retrieval and recommendation."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class FreshnessStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class JobPosting(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    source: str
    source_url: str
    title: str
    company: str
    location: str
    salary: str | None = None
    target_direction: str
    responsibilities: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    posted_at: datetime | None = None
    expiry_at: datetime | None = None
    freshness_status: FreshnessStatus = FreshnessStatus.UNKNOWN
    fetched_at: datetime
    source_links: list[str] = Field(default_factory=list)
