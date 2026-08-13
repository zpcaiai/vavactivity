"""Administrative dashboard API (B18).

Every route is permission-gated server-side. Hiding a button in the admin UI is
never the control (AUTH-002); the checks below are.
"""

# ruff: noqa: B008, E501

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.identity.dependencies import AuthenticatedPrincipal
from vav.modules.identity.permissions import require_permission
from vav.modules.member_dashboard import service
from vav.modules.member_dashboard.schemas import TaskTypeOverrideRequest

router = APIRouter(prefix="/admin")


@router.get("/dashboard/incidents")
async def section_incidents(
    request: Request,
    section: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _principal: AuthenticatedPrincipal = Depends(
        require_permission("member_dashboard.incidents.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Which sections have been degrading, and with which error code."""

    return success(
        await service.list_section_incidents(session, section=section, limit=limit, offset=offset),
        request_id_from_request(request),
    )


@router.get("/dashboard/task-types")
async def task_type_overrides(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(
        require_permission("member_dashboard.task_types.manage")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.list_task_type_overrides(session), request_id_from_request(request)
    )


@router.put("/dashboard/task-types")
async def set_task_type_override(
    payload: TaskTypeOverrideRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("member_dashboard.task_types.manage")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.upsert_task_type_override(
            session, actor_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


@router.get("/dashboard/members/{user_id}")
async def member_dashboard_preview(
    user_id: UUID,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(
        require_permission("member_dashboard.preview.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Render a member's dashboard exactly as they see it, for support calls.

    This reuses the member path rather than a parallel query set: a support
    agent must not be able to see a section the member cannot, and the surest
    way to guarantee that is to run the same code.
    """

    return success(
        await service.preview_member_dashboard(session, user_id=user_id),
        request_id_from_request(request),
    )
