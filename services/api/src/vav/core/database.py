from __future__ import annotations

from functools import lru_cache
from typing import cast

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from vav.common.exceptions import VavError
from vav.core.config import get_settings


def asyncpg_engine_configuration(database_url: str) -> tuple[URL, dict[str, object]]:
    """Normalize platform Postgres URLs and translate TLS options for asyncpg."""
    url = make_url(database_url)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+asyncpg")
    if url.drivername != "postgresql+asyncpg":
        return url, {}

    ssl_mode = url.query.get("sslmode")
    url = url.difference_update_query(["sslmode", "channel_binding"])
    if ssl_mode is None:
        return url, {}
    if not isinstance(ssl_mode, str):
        ssl_mode = ssl_mode[-1]
    return url, {"ssl": ssl_mode}


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    database_url, connect_args = asyncpg_engine_configuration(settings.database_url)
    if settings.environment == "test":
        return create_async_engine(
            database_url,
            connect_args=connect_args,
            pool_pre_ping=True,
            poolclass=NullPool,
        )
    return create_async_engine(
        database_url,
        connect_args=connect_args,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
    )


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


def session_factory() -> AsyncSession:
    return get_session_factory()()


@lru_cache
def get_redis() -> Redis:
    redis_url = get_settings().redis_url
    if not redis_url:
        raise VavError(
            "REDIS_NOT_CONFIGURED",
            "Redis-backed functionality is unavailable.",
            status_code=503,
        )
    return cast(Redis, Redis.from_url(redis_url, decode_responses=True))


def redis_is_configured() -> bool:
    return bool(get_settings().redis_url)


async def check_database() -> None:
    async with get_engine().connect() as connection:
        await connection.execute(text("SELECT 1"))


async def check_redis() -> None:
    await get_redis().ping()


async def close_resources() -> None:
    if get_redis.cache_info().currsize:
        redis = get_redis()
        await redis.aclose()
        get_redis.cache_clear()
    if get_engine.cache_info().currsize:
        engine = get_engine()
        await engine.dispose()
        get_session_factory.cache_clear()
        get_engine.cache_clear()
