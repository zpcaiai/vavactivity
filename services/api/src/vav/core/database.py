from __future__ import annotations

from functools import lru_cache
from typing import cast

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from vav.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    if settings.environment == "test":
        return create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            poolclass=NullPool,
        )
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_recycle=1800,
    )


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


def session_factory() -> AsyncSession:
    return get_session_factory()()


@lru_cache
def get_redis() -> Redis:
    return cast(Redis, Redis.from_url(get_settings().redis_url, decode_responses=True))


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
