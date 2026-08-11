from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from vav.common.schemas import success
from vav.core.database import check_database, check_redis, redis_is_configured
from vav.core.metrics import registry
from vav.core.request_context import request_id_from_request

router = APIRouter()


@router.get("/startup", summary="Startup configuration status")
async def startup(request: Request) -> dict[str, Any]:
    return success(
        {"status": "ok", "checks": {"configuration": "ok", "routers": "ok"}},
        request_id_from_request(request),
    )


@router.get("/metrics", include_in_schema=False)
async def metrics() -> PlainTextResponse:
    return PlainTextResponse(registry.render(), media_type="text/plain; version=0.0.4")


@router.get("/live", summary="Process liveness")
async def liveness(request: Request) -> dict[str, Any]:
    return success({"status": "ok"}, request_id_from_request(request))


@router.get("/ready", summary="Dependency readiness")
async def readiness(request: Request) -> JSONResponse:
    checks = {"postgresql": check_database}
    redis_configured = redis_is_configured()
    if redis_configured:
        checks["redis"] = check_redis

    async def run_check(name: str) -> tuple[str, str]:
        try:
            await asyncio.wait_for(checks[name](), timeout=3)
            return name, "ok"
        except Exception:
            return name, "unavailable"

    results = dict(await asyncio.gather(*(run_check(name) for name in checks)))
    if not redis_configured:
        results["redis"] = "disabled"
    is_ready = all(status in {"ok", "disabled"} for status in results.values())
    body = success(
        {"status": "ok" if is_ready else "unavailable", "dependencies": results},
        request_id_from_request(request),
    )
    return JSONResponse(status_code=200 if is_ready else 503, content=body)
