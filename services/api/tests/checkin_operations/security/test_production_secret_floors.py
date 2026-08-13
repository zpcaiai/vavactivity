"""Production must refuse to boot on the repository's development secrets.

Each secret below is the only thing making a capability unforgeable. Their
defaults are published in this repository, so a deployment that forgets to
override one does not degrade — it hands out a capability anyone can mint. The
failure has to happen at startup, because none of these produce a visible
symptom at runtime.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from vav.core.config import Settings

PRODUCTION_BASE: dict[str, object] = {
    "APP_ENV": "production",
    "DATABASE_URL": (
        "postgresql+asyncpg://vav:strong@db.example.com/vav?sslmode=require&channel_binding=require"
    ),
    "REDIS_URL": "rediss://cache.example.com:6379/0",
    "DEBUG": "false",
    "APP_CORS_ORIGINS": ["https://app.example.com"],
    "MEDIA_S3_ENDPOINT": "https://s3.example.com",
    "BACKUP_ENCRYPTION_KEY": "production-backup-key",
    "AUTH_REFRESH_TOKEN_PEPPER": "production-refresh-pepper",
    "AUTH_COOKIE_SECURE": "true",
    "AUTH_EMAIL_VERIFICATION_REQUIRED": "true",
    "PAYMENT_TEST_FAKE_ENABLED": "false",
    "COURSE_VIDEO_PROVIDER": "cloudflare_stream",
    "COUNSELING_MEETING_PROVIDER": "tencent_meeting",
    "KNOWLEDGE_EMBEDDING_PROVIDER": "openai",
    "AI_MODEL_PROVIDER": "openai",
    "AI_CONVERSATION_ENCRYPTION_ENABLED": "true",
    "NOTIFICATION_EMAIL_PROVIDER": "ses",
    "NOTIFICATION_EMAIL_PROVIDER_WEBHOOK_SECRET": "production-webhook-secret",
    "PRIVACY_SEARCH_HMAC_PEPPER": "production-search-pepper",
}

#: The secrets introduced by batches B13-B19, none of which had a production
#: floor before. Each entry is the environment variable and a real-looking
#: replacement value.
NEW_SECRETS = {
    "CHECKIN_LAST_FOUR_HMAC_KEY": "production-last-four-key",
    "CHECKIN_TOKEN_SIGNING_KEY": "production-checkin-token-key",
    "SHARE_LINK_SECRET": "production-share-link-secret",
    "PROFILE_MEDIA_TOKEN_SECRET": "production-profile-media-secret",
    "DISCOVERY_IP_MARKER_SALT": "production-ip-marker-salt",
}


def _production(**overrides: object) -> Settings:
    return Settings(**{**PRODUCTION_BASE, **NEW_SECRETS, **overrides})  # type: ignore[arg-type]


def test_a_fully_configured_production_environment_is_accepted() -> None:
    """Guards the negative cases below from passing for the wrong reason."""

    settings = _production()
    assert settings.environment == "production"


@pytest.mark.parametrize("name", sorted(NEW_SECRETS))
def test_production_rejects_the_shipped_default_secret(name: str) -> None:
    default = Settings().model_dump()
    with pytest.raises(ValidationError) as error:
        _production(**{name: _default_value_for(name, default)})
    assert name in str(error.value)


@pytest.mark.parametrize("name", sorted(NEW_SECRETS))
def test_production_rejects_a_blank_secret(name: str) -> None:
    with pytest.raises(ValidationError) as error:
        _production(**{name: "   "})
    assert name in str(error.value)


def _default_value_for(name: str, dumped: dict[str, object]) -> str:
    """Return the repository default for ``name`` without hardcoding it here."""

    attribute = {
        "CHECKIN_LAST_FOUR_HMAC_KEY": "checkin_last_four_hmac_key",
        "CHECKIN_TOKEN_SIGNING_KEY": "checkin_token_signing_key",
        "SHARE_LINK_SECRET": "share_link_secret",
        "PROFILE_MEDIA_TOKEN_SECRET": "profile_media_token_secret",
        "DISCOVERY_IP_MARKER_SALT": "discovery_ip_marker_salt",
    }[name]
    secret = getattr(Settings(), attribute)
    return str(secret.get_secret_value())


def test_non_production_still_boots_on_development_secrets() -> None:
    """Local development must stay zero-configuration."""

    settings = Settings(APP_ENV="development")  # type: ignore[arg-type]
    assert "change-me" in settings.checkin_last_four_hmac_key.get_secret_value()
