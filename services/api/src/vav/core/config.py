from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Literal["development", "test", "staging", "production"] = Field(
        default="development", validation_alias="APP_ENV"
    )
    version: str = Field(default="0.1.0", validation_alias="APP_VERSION")
    log_level: str = Field(default="INFO", validation_alias="APP_LOG_LEVEL")
    display_timezone: str = Field(default="Asia/Shanghai", validation_alias="APP_DISPLAY_TIMEZONE")
    cors_origins: list[AnyHttpUrl] = Field(
        default_factory=lambda: [
            AnyHttpUrl("http://localhost:5173"),
            AnyHttpUrl("http://localhost:5174"),
        ],
        validation_alias="APP_CORS_ORIGINS",
    )
    database_url: str = Field(
        default=("postgresql+asyncpg://vav:vav_local_development_only@localhost:5432/vav"),
        validation_alias="DATABASE_URL",
        repr=False,
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias="REDIS_URL",
        repr=False,
    )
    otel_endpoint: str | None = Field(default=None, validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    ai_enabled: bool = Field(default=False, validation_alias="AI_ENABLED")

    @model_validator(mode="after")
    def reject_development_credentials_in_production(self) -> Settings:
        if self.environment == "production" and (
            "local_development_only" in self.database_url or "localhost" in self.database_url
        ):
            raise ValueError("production cannot use development database credentials")
        return self

    def public_summary(self) -> dict[str, object]:
        return {
            "environment": self.environment,
            "version": self.version,
            "display_timezone": self.display_timezone,
            "features": {"ai_assistant": self.ai_enabled},
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
