"""Environment-based application settings."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite://jobscout.sqlite3"
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-flash"
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = Field(default="", repr=False)
    llm_timeout: float = Field(default=30.0, gt=0, le=180, allow_inf_nan=False)
    llm_max_tokens: int = Field(default=4096, ge=1, le=32768)
    llm_retry_delay: float = Field(default=0.25, ge=0, le=5, allow_inf_nan=False)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
