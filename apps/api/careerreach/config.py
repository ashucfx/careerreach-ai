from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CAREERREACH_", env_file=".env", extra="ignore")

    environment: str = "development"
    model_base_url: str = "https://api.openai.com/v1"
    model_api_key: SecretStr | None = None
    reasoning_model: str = "gpt-4.1"
    communication_model: str = "gpt-4.1-mini"
    extraction_model: str = "gpt-4.1-mini"
    model_fallback: str | None = None
    model_timeout_seconds: float = 30.0
    model_max_retries: int = 2


@lru_cache
def get_settings() -> Settings:
    return Settings()
