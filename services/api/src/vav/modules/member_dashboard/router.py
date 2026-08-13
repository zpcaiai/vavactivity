"""Member-facing dashboard API (B18).

Every route resolves the member from the authenticated principal. There is no
``user_id`` path or query parameter anywhere in this file, which is the
simplest way to make cross-member access impossible: there is nothing to
tamper with.
"""

# ruff: noqa: B008, E501

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_authenticated_user
from vav.modules.member_dashboard import service
from vav.modules.member_dashboard.schemas import (
    DashboardPreferencesRequest,
    TaskDismissRequest,
)

router = APIRouter(prefix="/account")


@router.get("/dashboard")
async def dashboard(
    request: Request,
    locale: str = Query(default="zh-CN", max_length=16),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """The aggregate view.

    Returns 200 with a ``degraded`` list whenever a source module is down; it
    does not return 5xx for a partial failure.
    """

    return success(
        await service.get_dashboard(
            session, user_id=principal.user.id, locale=locale, limit=limit, offset=offset
        ),
        request_id_from_request(request),
    )


@router.get("/dashboard/sections/{section}")
async def dashboard_section(
    section: str,
    request: Request,
    locale: str = Query(default="zh-CN", max_length=16),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_section(
            session,
            user_id=principal.user.id,
            section=section,
            locale=locale,
            limit=limit,
            offset=offset,
        ),
        request_id_from_request(request),
    )


@router.get("/dashboard/preferences")
async def preferences(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_preferences(session, principal.user.id),
        request_id_from_request(request),
    )


@router.put("/dashboard/preferences")
async def set_preferences(
    payload: DashboardPreferencesRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.set_preferences(
            session, user_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


@router.post("/dashboard/dismissals")
async def dismiss_task(
    payload: TaskDismissRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.dismiss_task(
            session, user_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


@router.delete("/dashboard/dismissals/{task_key}")
async def restore_task(
    task_key: str,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.restore_task(session, user_id=principal.user.id, task_key=task_key),
        request_id_from_request(request),
    )
