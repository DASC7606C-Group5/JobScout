"""Raw job records, search results and errors returned by source adapters."""

from pydantic import AwareDatetime, BaseModel, Field, JsonValue

from jobscout.schemas.errors import WorkflowError
from jobscout.schemas.notices import ApplicantNotice
from jobscout.schemas.wire import WireModel


class RawJob(BaseModel):
    source: str
    source_url: str | None = None
    fetched_at: AwareDatetime
    target_direction: str
    source_job_id: str | None = None
    title: str | None = None
    company: str | None = None
    location: str | None = None
    salary: str | None = None
    description: str | None = None
    description_is_excerpt: bool = False
    employment_type: str | None = None
    posted_at: str | int | float | None = None
    expiry_at: str | int | float | None = None
    raw_payload: dict[str, JsonValue]


class SourceOutcome(WireModel):
    request_index: int = 0
    target_direction: str
    source: str
    candidate_count: int = 0
    returned_count: int = 0
    incomplete_count: int = 0
    excerpt_count: int = 0
    elapsed_seconds: float = 0
    status: str = "ok"


class SearchResult(BaseModel):
    raw_jobs: list[RawJob] = Field(default_factory=list)
    errors: list[WorkflowError] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    notices: list[ApplicantNotice] = Field(default_factory=list)
    outcomes: list[SourceOutcome] = Field(default_factory=list)


class RetrievalFailure(Exception):
    """Safe message only: never include response bodies or credential-bearing URLs."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def workflow_error(code: str, message: str, **details: str | int) -> WorkflowError:
    return WorkflowError(code=code, message=message, stage="search", details=dict(details))
