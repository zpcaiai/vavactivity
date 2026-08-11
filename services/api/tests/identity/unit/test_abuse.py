from __future__ import annotations

import pytest

from vav.common.exceptions import VavError
from vav.modules.identity import abuse


@pytest.mark.asyncio
async def test_redis_free_rate_limit_uses_bounded_local_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 100.0
    limiter = abuse.InMemoryRateLimiter(max_entries=2, clock=lambda: now)
    monkeypatch.setattr(abuse, "redis_is_configured", lambda: False)
    monkeypatch.setattr(abuse, "local_rate_limiter", limiter)

    await abuse.enforce_rate_limit("login:user", limit=2, window_seconds=60)
    await abuse.enforce_rate_limit("login:user", limit=2, window_seconds=60)

    with pytest.raises(VavError) as exc_info:
        await abuse.enforce_rate_limit("login:user", limit=2, window_seconds=60)

    assert exc_info.value.code == "RATE_LIMITED"
    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_local_rate_limit_reopens_and_remains_bounded() -> None:
    now = 100.0
    limiter = abuse.InMemoryRateLimiter(max_entries=2, clock=lambda: now)

    await limiter.enforce("first", limit=1, window_seconds=10)
    await limiter.enforce("second", limit=1, window_seconds=20)
    await limiter.enforce("third", limit=1, window_seconds=30)

    assert len(limiter._windows) == 2
    assert "first" not in limiter._windows

    now = 131.0
    await limiter.enforce("third", limit=1, window_seconds=30)

    assert len(limiter._windows) == 1
    assert limiter._windows["third"][0] == 1
