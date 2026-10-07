"""Public account model settings and daily operation allowance."""

from typing import Literal

from pydantic import Field

from .wire import WireModel


class ModelInfo(WireModel):
    personal: bool
    endpoint_id: str | None
    model: str
    key_configured: bool
    server_provider: str
    server_model: str
    server_key_configured: bool
    thinking: bool
    server_thinking: bool
    thinking_level: str
    server_thinking_level: str


class ModelRoles(WireModel):
    semantic: ModelInfo
    decision: ModelInfo


class ModelEndpoint(WireModel):
    id: str
    name: str
    thinking_supported: bool
    thinking_level_supported: bool


class ModelSettingsResponse(WireModel):
    roles: ModelRoles
    endpoints: list[ModelEndpoint]
    personal_available: bool


class DailyUsage(WireModel):
    enabled: Literal[True]
    remaining: int = Field(ge=0)
    used: int = Field(ge=0)
    limit: int = Field(ge=0)
    server_remaining: int = Field(ge=0)
    day: str
    timezone: str


class DisabledUsage(WireModel):
    enabled: Literal[False]
