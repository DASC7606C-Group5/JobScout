"""Model call counts, token usage and timing; excludes prompts, credentials and reasoning."""

from pydantic import BaseModel, ConfigDict, Field


class ModelUsage(BaseModel):
    """Cumulative counters for a provider instance, including failed/repair requests."""

    model_config = ConfigDict(extra="forbid")

    structured_calls: int = Field(default=0, ge=0)
    successful_calls: int = Field(default=0, ge=0)
    failed_calls: int = Field(default=0, ge=0)
    cancellations: int = Field(default=0, ge=0)
    requests: int = Field(default=0, ge=0)
    retries: int = Field(default=0, ge=0)
    repairs: int = Field(default=0, ge=0)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
