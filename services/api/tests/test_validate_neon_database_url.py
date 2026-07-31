from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

VALID_URL = (
    "postgresql+asyncpg://vav_owner:secret@"
    "ep-example.ap-southeast-1.aws.neon.tech/vav?sslmode=require"
)
VALIDATOR = Path(__file__).parents[3] / "scripts" / "validate_neon_database_url.py"


def run_validator(value: str | None) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    if value is None:
        environment.pop("NEON_DATABASE_URL", None)
    else:
        environment["NEON_DATABASE_URL"] = value
    return subprocess.run(
        [sys.executable, str(VALIDATOR)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def test_accepts_direct_tls_neon_url() -> None:
    result = run_validator(VALID_URL)

    assert result.returncode == 0
    assert result.stdout.strip() == "Neon migration connection validated"


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
    result = run_validator(value)

    assert result.returncode == 1
    assert message in result.stderr
