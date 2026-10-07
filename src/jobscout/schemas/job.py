"""Job posting fields shared by search and recommendation services."""

from datetime import datetime
from enum import StrEnum

from pydantic import ConfigDict, Field

from jobscout.schemas.wire import WireModel


class FreshnessStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class SourceDocument(WireModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    source: str
    source_url: str
    text: str
    fetched_at: datetime
    is_excerpt: bool = False


class JobPosting(WireModel):
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
    source_documents: list[SourceDocument] = Field(default_factory=list)
    description: str = ""
    description_is_excerpt: bool = False
    employment_type: str | None = None
    target_directions: list[str] = Field(default_factory=list)

    def has_full_description(self) -> bool:
        return bool(self.description.strip() and not self.description_is_excerpt) or any(
            document.text.strip()
            and not document.is_excerpt
            and not document.document_id.endswith(":metadata")
            for document in self.source_documents
        )
