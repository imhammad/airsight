"""Application settings, read from environment variables and, for local development, .env."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://airsight:airsight@localhost:5432/airsight"
    redis_url: str = "redis://localhost:6379/0"

    purpleair_key: SecretStr | None = None
    airnow_key: SecretStr | None = None

    http_timeout_seconds: float = 30.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
