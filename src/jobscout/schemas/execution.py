"""Public progress facts for one confirmed search execution."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

StopReason = Literal[
    "results_ready",
    "target_reached",
    "source_exhausted",
    "budget_exhausted",
    "user_stopped",
    "error",
]


class SearchEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    action: str
    message: str
    source: str | None = None


class SearchProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(default=0, ge=0)
    analyzed_count: int = Field(default=0, ge=0)
    matched_count: int = Field(default=0, ge=0)
    pending_count: int = Field(default=0, ge=0)
    elapsed_seconds: float = Field(default=0, ge=0)
    retrieval_stopped: bool = False
    events: list[SearchEvent] = Field(default_factory=list)
