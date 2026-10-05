"""Shared error contract for workflow and HTTP responses."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class WorkflowError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    stage: str
    details: dict[str, str | int | float | bool | None] | None = None


class ApplicantError(BaseModel):
    """Public recovery contract; internal stages and diagnostic details stay on the server."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    action: Literal["retry", "edit_conditions", "reload", "start_new_search"] | None = None
