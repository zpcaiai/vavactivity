from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from vav.core.config import Settings


def production_values() -> dict[str, Any]:
    return {
        "APP_ENV": "production",
        "APP_DEBUG": False,
        "APP_CORS_ORIGINS": ["https://web.example"],
        "DATABASE_URL": ("postgresql+asyncpg://user:secret@db.example/vav?sslmode=require"),
        "REDIS_URL": "rediss://redis.example/0",
        "MEDIA_S3_ENDPOINT": "https://s3.example",
        "BACKUP_ENCRYPTION_KEY": "render-generated-backup-key",
        "AUTH_REFRESH_TOKEN_PEPPER": "render-generated-refresh-pepper",
        "AUTH_COOKIE_SECURE": True,
        "PAYMENT_TEST_FAKE_ENABLED": False,
        "COURSE_VIDEO_PROVIDER": "approved_private",
        "COUNSELING_MEETING_PROVIDER": "approved",
        "KNOWLEDGE_EMBEDDING_PROVIDER": "approved",
        "AI_MODEL_PROVIDER": "approved",
        "AI_CONVERSATION_ENCRYPTION_ENABLED": True,
        "NOTIFICATION_EMAIL_PROVIDER": "transactional",
        "NOTIFICATION_EMAIL_PROVIDER_WEBHOOK_SECRET": "render-generated-webhook-secret",
        "PRIVACY_SEARCH_HMAC_PEPPER": "render-generated-privacy-pepper",
    }


def test_production_requires_explicit_runtime_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    values = production_values()
    values.pop("DATABASE_URL")

    with pytest.raises(ValidationError, match="production requires an explicit DATABASE_URL"):
        Settings(_env_file=None, **values)


def test_neon_migration_url_does_not_replace_runtime_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "NEON_DATABASE_URL",
        "postgresql+asyncpg://user:secret@db.example/vav?sslmode=require",
    )
    values = production_values()
    values.pop("DATABASE_URL")

    with pytest.raises(ValidationError, match="production requires an explicit DATABASE_URL"):
        Settings(_env_file=None, **values)


def test_complete_render_production_baseline_is_accepted() -> None:
    settings = Settings(_env_file=None, **production_values())

    assert settings.environment == "production"
    assert settings.payment_test_fake_enabled is False


def test_production_allows_redis_to_be_omitted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    values = production_values()
    values.pop("REDIS_URL")

    settings = Settings(_env_file=None, **values)

    assert settings.redis_url is None
