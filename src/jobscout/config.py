"""Environment-based application settings."""

from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    production: bool = False
    public_origin: str = "http://localhost:3000"
    credentials_key: SecretStr = SecretStr("")
    cookie_secure: bool = False
    frontend_directory: str = "web/dist"
    server_daily_user_limit: int = Field(default=20, ge=1)
    server_daily_total_limit: int = Field(default=200, ge=1)
    concurrent_user_limit: int = Field(default=1, ge=1)
    concurrent_total_limit: int = Field(default=3, ge=1)
    model_endpoints: dict[str, dict[str, str]] = Field(default_factory=dict)
    database_url: str = "sqlite://jobscout.sqlite3"
    llm_semantic_provider: str = "deepseek"
    llm_semantic_model: str = "deepseek-flash"
    llm_semantic_base_url: str = "https://api.deepseek.com"
    llm_semantic_api_key: str = Field(default="", repr=False)
    llm_semantic_thinking: bool = False
    llm_decision_provider: str = "deepseek"
    llm_decision_model: str = "deepseek-flash"
    llm_decision_base_url: str = "https://api.deepseek.com"
    llm_decision_api_key: str = Field(default="", repr=False)
    llm_decision_thinking: bool = False
    llm_timeout: float = Field(default=120.0, gt=0, le=180, allow_inf_nan=False)
    llm_max_tokens: int = Field(default=16384, ge=1, le=32768)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    @model_validator(mode="after")
    def validate_deployment(self) -> Settings:
        import httpx
        from cryptography.fernet import Fernet

        origin = httpx.URL(self.public_origin)
        if (
            not origin.host
            or origin.scheme not in {"http", "https"}
            or origin.userinfo
            or origin.query
            or origin.fragment
            or origin.path != "/"
        ):
            raise ValueError("PUBLIC_ORIGIN must be an origin without a path.")
        if self.production and (
            origin.scheme != "https"
            or not self.cookie_secure
            or not self.credentials_key.get_secret_value()
        ):
            raise ValueError("Production requires HTTPS, secure cookies and CREDENTIALS_KEY.")
        if self.credentials_key.get_secret_value():
            Fernet(self.credentials_key.get_secret_value().encode())
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
