"""Shared error contract for workflow and HTTP responses."""

from pydantic import BaseModel, ConfigDict


class WorkflowError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    stage: str
    details: dict[str, str | int | float | bool | None] | None = None
