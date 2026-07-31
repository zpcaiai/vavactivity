#!/usr/bin/env python3
"""Validate the secret used by the production Neon migration gate."""

from __future__ import annotations

import os
import sys
from urllib.parse import parse_qs, urlsplit


class NeonDatabaseURLValidationError(ValueError):
    """Raised when the migration URL is missing or unsafe for this project."""


def validate_neon_database_url(value: str | None) -> None:
    if not value:
        raise NeonDatabaseURLValidationError(
            "NEON_DATABASE_URL is not configured as a GitHub Actions secret"
        )

    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname or ""
    except ValueError as exc:
        raise NeonDatabaseURLValidationError(
            "NEON_DATABASE_URL is not a valid URL"
        ) from exc

    if parsed.scheme != "postgresql+asyncpg":
        raise NeonDatabaseURLValidationError(
            "NEON_DATABASE_URL must use the postgresql+asyncpg driver"
        )
    if not parsed.username or not parsed.password or not parsed.path.strip("/"):
        raise NeonDatabaseURLValidationError(
            "NEON_DATABASE_URL must include a role, password, and database"
        )
    if not hostname.endswith(".neon.tech"):
        raise NeonDatabaseURLValidationError(
            "NEON_DATABASE_URL must target a Neon host"
        )
    if "-pooler." in hostname:
        raise NeonDatabaseURLValidationError(
            "NEON_DATABASE_URL must use a direct connection for schema migrations"
        )

    query = parse_qs(parsed.query, keep_blank_values=True)
    if query.get("sslmode") != ["require"]:
        raise NeonDatabaseURLValidationError(
            "NEON_DATABASE_URL must include sslmode=require"
        )
    if "channel_binding" in query:
        raise NeonDatabaseURLValidationError(
            "NEON_DATABASE_URL must omit channel_binding for asyncpg compatibility"
        )


def main() -> int:
    try:
        validate_neon_database_url(os.environ.get("NEON_DATABASE_URL"))
    except NeonDatabaseURLValidationError as exc:
        print(f"Neon migration configuration error: {exc}", file=sys.stderr)
        return 1

    print("Neon migration connection validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
