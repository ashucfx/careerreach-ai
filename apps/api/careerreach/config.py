from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CAREERREACH_", env_file=".env", env_ignore_empty=True, extra="ignore"
    )

    environment: str = "development"
    model_base_url: str = "https://api.openai.com/v1"
    model_api_key: SecretStr | None = None
    reasoning_model: str = "gpt-4.1"
    communication_model: str = "gpt-4.1-mini"
    extraction_model: str = "gpt-4.1-mini"
    model_fallback: str | None = None
    brave_search_api_key: SecretStr | None = None
    model_timeout_seconds: float = 30.0
    model_max_retries: int = 2
    database_url: str | None = None
    migration_database_url: str | None = None
    runtime_database_user: str | None = None
    runtime_database_password: SecretStr | None = None
    auth_signing_key: SecretStr | None = None
    auth_token_ttl_minutes: int = Field(default=15, gt=0, le=1440)
    auth_issuer: str = "careerreach-api"
    auth_audience: str = "careerreach-user"
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "careerreach-workflows"


@lru_cache
def get_settings() -> Settings:
    return Settings()
