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
        "MEDIA_S3_PUBLIC_ENDPOINT": "https://media.example",
        "MEDIA_S3_ACCESS_KEY": "production-media-access-key",
        "MEDIA_S3_SECRET_KEY": "production-media-secret-key",
        "BACKUP_ENCRYPTION_KEY": "render-generated-backup-key",
        "AUTH_REFRESH_TOKEN_PEPPER": "render-generated-refresh-pepper",
        "AUTH_COOKIE_SECURE": True,
        "PAYMENT_TEST_FAKE_ENABLED": False,
        "COURSE_VIDEO_PROVIDER": "approved_private",
        "COUNSELING_MEETING_PROVIDER": "approved",
        "KNOWLEDGE_EMBEDDING_PROVIDER": "approved",
        "AI_MODEL_PROVIDER": "gemini",
        "AI_MODEL_NAME": "gemini-3.6-flash",
        "GEMINI_API_KEY": "test-gemini-key",
        "AI_CONVERSATION_ENCRYPTION_ENABLED": True,
        "NOTIFICATION_EMAIL_PROVIDER": "transactional",
        "NOTIFICATION_EMAIL_PROVIDER_WEBHOOK_SECRET": "render-generated-webhook-secret",
        "PRIVACY_SEARCH_HMAC_PEPPER": "render-generated-privacy-pepper",
        # Batch B13-B19 secrets. Each is the only thing making a capability
        # unforgeable, so production refuses to boot on the repository default
        # and the deployment config (render.yaml, the Kubernetes secret
        # reference, the compose file and config/env/*.yaml) provisions all
        # five. This baseline mirrors that config: if a key is added here it
        # has to exist there too, or "complete baseline" stops being true.
        "CHECKIN_LAST_FOUR_HMAC_KEY": "render-generated-last-four-key",
        "CHECKIN_TOKEN_SIGNING_KEY": "render-generated-checkin-token-key",
        "SHARE_LINK_SECRET": "render-generated-share-link-secret",
        "PROFILE_MEDIA_TOKEN_SECRET": "render-generated-profile-media-secret",
        "DISCOVERY_IP_MARKER_SALT": "render-generated-ip-marker-salt",
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
    assert settings.database_pool_size == 5
    assert settings.database_max_overflow == 10
    assert settings.payment_test_fake_enabled is False


def test_database_pool_limits_are_configurable() -> None:
    settings = Settings(
        _env_file=None,
        DATABASE_POOL_SIZE=2,
        DATABASE_MAX_OVERFLOW=0,
    )

    assert settings.database_pool_size == 2
    assert settings.database_max_overflow == 0


@pytest.mark.parametrize("value", [None, "http://media.example"])
def test_production_requires_an_explicit_https_browser_storage_endpoint(
    value: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MEDIA_S3_PUBLIC_ENDPOINT", raising=False)
    values = production_values()
    if value is None:
        values.pop("MEDIA_S3_PUBLIC_ENDPOINT")
    else:
        values["MEDIA_S3_PUBLIC_ENDPOINT"] = value

    with pytest.raises(ValidationError, match="MEDIA_S3_PUBLIC_ENDPOINT"):
        Settings(_env_file=None, **values)


def test_production_cannot_disable_email_verification() -> None:
    values = production_values()
    values["AUTH_EMAIL_VERIFICATION_REQUIRED"] = False

    with pytest.raises(ValidationError, match="production requires email verification"):
        Settings(_env_file=None, **values)


def test_production_allows_redis_to_be_omitted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    values = production_values()
    values.pop("REDIS_URL")

    settings = Settings(_env_file=None, **values)

    assert settings.redis_url is None
