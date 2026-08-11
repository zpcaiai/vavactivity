from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from starlette.requests import Request

from vav.common.exceptions import VavError
from vav.core import database
from vav.modules.health import router as health_router


def test_get_redis_fails_closed_when_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    database.get_redis.cache_clear()
    monkeypatch.setattr(database, "get_settings", lambda: SimpleNamespace(redis_url=None))

    with pytest.raises(VavError, match="Redis-backed functionality is unavailable") as exc_info:
        database.get_redis()

    assert exc_info.value.code == "REDIS_NOT_CONFIGURED"
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_readiness_accepts_disabled_optional_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def healthy_database() -> None:
        return None

    monkeypatch.setattr(health_router, "check_database", healthy_database)
    monkeypatch.setattr(health_router, "redis_is_configured", lambda: False)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/health/ready",
            "headers": [],
        }
    )

    response = await health_router.readiness(request)
    body: dict[str, Any] = json.loads(bytes(response.body))

    assert response.status_code == 200
    assert body["data"] == {
        "status": "ok",
        "dependencies": {"postgresql": "ok", "redis": "disabled"},
    }
