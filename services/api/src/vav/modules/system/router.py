from typing import Any

from fastapi import APIRouter, Request

from vav.common.schemas import success
from vav.core.config import get_settings
from vav.core.request_context import request_id_from_request

router = APIRouter()


@router.get("/version", summary="Application version")
async def version(request: Request) -> dict[str, Any]:
    settings = get_settings()
    return success(
        {"name": "vav-platform-api", "version": settings.version},
        request_id_from_request(request),
    )


@router.get("/config", summary="Non-secret runtime configuration")
async def public_config(request: Request) -> dict[str, Any]:
    return success(get_settings().public_summary(), request_id_from_request(request))
