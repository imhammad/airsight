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
    # Port 5001 on the host: macOS uses 5000 for AirPlay
    mlflow_tracking_uri: str = "http://localhost:5001"

    purpleair_key: SecretStr | None = None
    airnow_key: SecretStr | None = None

    http_timeout_seconds: float = 30.0

    # Public API (ADR 0008)
    rate_limit_per_minute: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
