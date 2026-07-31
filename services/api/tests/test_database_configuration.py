from __future__ import annotations

from vav.core.database import asyncpg_engine_configuration


def test_translates_neon_tls_options_for_asyncpg() -> None:
    url, connect_args = asyncpg_engine_configuration(
        "postgresql+asyncpg://owner:secret@"
        "ep-example.ap-southeast-1.aws.neon.tech/vav"
        "?channel_binding=require&sslmode=require"
    )

    assert url.drivername == "postgresql+asyncpg"
    assert url.host == "ep-example.ap-southeast-1.aws.neon.tech"
    assert "sslmode" not in url.query
    assert "channel_binding" not in url.query
    assert connect_args == {"ssl": "require"}


def test_preserves_non_asyncpg_database_urls() -> None:
    url, connect_args = asyncpg_engine_configuration("postgresql://owner:secret@localhost/vav")

    assert url.drivername == "postgresql"
    assert connect_args == {}
