from __future__ import annotations

from vav.common.exceptions import VavError
from vav.core.database import get_redis


async def enforce_rate_limit(key: str, *, limit: int, window_seconds: int) -> None:
    redis = get_redis()
    value = await redis.incr(key)
    if value == 1:
        await redis.expire(key, window_seconds)
    if value > limit:
        raise VavError(
            "RATE_LIMITED",
            "Too many requests. Try again later.",
            status_code=429,
        )
