from __future__ import annotations

import asyncio
import heapq
import time
from collections.abc import Callable

from vav.common.exceptions import VavError
from vav.core.database import get_redis, redis_is_configured

MAX_LOCAL_RATE_LIMIT_KEYS = 10_000


class InMemoryRateLimiter:
    """Bounded fixed-window fallback for single-instance Redis-free deployments."""

    def __init__(
        self,
        *,
        max_entries: int = MAX_LOCAL_RATE_LIMIT_KEYS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_entries = max_entries
        self.clock = clock
        self._windows: dict[str, tuple[int, float]] = {}
        self._expirations: list[tuple[float, str]] = []
        self._lock = asyncio.Lock()

    def _drop_expired(self, now: float) -> None:
        while self._expirations and self._expirations[0][0] <= now:
            expires_at, key = heapq.heappop(self._expirations)
            current = self._windows.get(key)
            if current is not None and current[1] == expires_at:
                del self._windows[key]

    def _evict_earliest(self) -> None:
        while self._expirations:
            expires_at, key = heapq.heappop(self._expirations)
            current = self._windows.get(key)
            if current is not None and current[1] == expires_at:
                del self._windows[key]
                return

    async def enforce(self, key: str, *, limit: int, window_seconds: int) -> None:
        now = self.clock()
        async with self._lock:
            self._drop_expired(now)
            current = self._windows.get(key)
            if current is None:
                if len(self._windows) >= self.max_entries:
                    self._evict_earliest()
                value = 1
                expires_at = now + window_seconds
                self._windows[key] = (value, expires_at)
                heapq.heappush(self._expirations, (expires_at, key))
            else:
                value = current[0] + 1
                self._windows[key] = (value, current[1])

        if value > limit:
            raise_rate_limited()


local_rate_limiter = InMemoryRateLimiter()


def raise_rate_limited() -> None:
    raise VavError(
        "RATE_LIMITED",
        "Too many requests. Try again later.",
        status_code=429,
    )


async def enforce_rate_limit(key: str, *, limit: int, window_seconds: int) -> None:
    if not redis_is_configured():
        await local_rate_limiter.enforce(key, limit=limit, window_seconds=window_seconds)
        return

    redis = get_redis()
    value = await redis.incr(key)
    if value == 1:
        await redis.expire(key, window_seconds)
    if value > limit:
        raise_rate_limited()
