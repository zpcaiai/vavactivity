# ruff: noqa: B008

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.identity.dependencies import AuthenticatedPrincipal
from vav.modules.identity.permissions import require_permission
from vav.modules.skills_platform import service
from vav.modules.skills_platform.schemas import ExecuteSkillRequest

router = APIRouter()


@router.get("/skills")
async def skills(
    request: Request,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(await service.list_skills(session), request_id_from_request(request))


@router.get("/skills/{skill_name}")
async def skill(
    skill_name: str,
    request: Request,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.skill_detail(session, skill_name), request_id_from_request(request)
    )


@router.get("/skills/{skill_name}/versions")
async def versions(
    skill_name: str,
    request: Request,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.skill_versions(session, skill_name), request_id_from_request(request)
    )


@router.get("/skill-versions/{version_id}")
async def version(
    version_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.version_detail(session, version_id), request_id_from_request(request)
    )


@router.post("/internal/skills/{skill_name}/execute")
async def execute(
    skill_name: str,
    payload: ExecuteSkillRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("skills.executions.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.queue_execution(session, principal.user.id, skill_name, payload),
        request_id_from_request(request),
    )
