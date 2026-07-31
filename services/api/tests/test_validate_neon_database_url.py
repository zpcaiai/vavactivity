from __future__ import annotations

import pytest
from scripts.validate_neon_database_url import (
    NeonDatabaseURLValidationError,
    validate_neon_database_url,
)

VALID_URL = (
    "postgresql+asyncpg://vav_owner:secret@"
    "ep-example.ap-southeast-1.aws.neon.tech/vav?sslmode=require"
)


def test_accepts_direct_tls_neon_url() -> None:
    validate_neon_database_url(VALID_URL)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (None, "not configured"),
        (VALID_URL.replace("postgresql+asyncpg", "postgresql"), "asyncpg driver"),
        (VALID_URL.replace(".neon.tech", "-pooler.neon.tech"), "direct connection"),
        (VALID_URL.replace(".neon.tech", ".example.com"), "Neon host"),
        (VALID_URL.replace("?sslmode=require", ""), "sslmode=require"),
        (
            f"{VALID_URL}&channel_binding=require",
            "omit channel_binding",
        ),
    ],
)
def test_rejects_unsafe_migration_urls(value: str | None, message: str) -> None:
    with pytest.raises(NeonDatabaseURLValidationError, match=message):
        validate_neon_database_url(value)
