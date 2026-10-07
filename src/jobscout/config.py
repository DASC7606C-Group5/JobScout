"""Environment-based application settings."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite://jobscout.sqlite3"
    llm_semantic_provider: str = "deepseek"
    llm_semantic_model: str = "deepseek-flash"
    llm_semantic_base_url: str = "https://api.deepseek.com"
    llm_semantic_api_key: str = Field(default="", repr=False)
    llm_decision_provider: str = "deepseek"
    llm_decision_model: str = "deepseek-flash"
    llm_decision_base_url: str = "https://api.deepseek.com"
    llm_decision_api_key: str = Field(default="", repr=False)
    llm_timeout: float = Field(default=120.0, gt=0, le=180, allow_inf_nan=False)
    llm_max_tokens: int = Field(default=16384, ge=1, le=32768)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
