"""Error codes, messages and recovery actions used by services and HTTP responses."""

from typing import Literal

from pydantic import ConfigDict

from jobscout.schemas.wire import WireModel


class WorkflowError(WireModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    stage: str
    details: dict[str, str | int | float | bool | None] | None = None


class ApplicantError(WireModel):
    """User-facing error and next action; internal stages and details stay on the server."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    action: Literal["retry", "edit_conditions", "reload", "start_new_search"] | None = None
