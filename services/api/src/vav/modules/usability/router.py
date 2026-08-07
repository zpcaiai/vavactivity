# ruff: noqa: B008, E501
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_authenticated_user
from vav.modules.usability import service
from vav.modules.usability.schemas import DraftSave, ImportPreview


router = APIRouter()


def _ok(value: Any, request: Request) -> dict[str, Any]:
    return success(value, request_id_from_request(request))


def _require_permission(principal: AuthenticatedPrincipal, permission: str) -> AuthenticatedPrincipal:
    principal.require(permission)
    return principal


@router.get("/usability/drafts")
async def list_user_drafts(
    request: Request,
    definition_code: str | None = None,
    include_expired: bool = False,
    limit: int = Query(100, ge=1, le=1000),
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    _require_permission(principal, "usability.drafts.read")
    return _ok(
        await service.list_user_drafts(
            session,
            principal.user.id,
            definition_code=definition_code,
            include_expired=include_expired,
            limit=limit,
        ),
        request,
    )


@router.get("/usability/drafts/{draft_id}")
async def get_user_draft(
    draft_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    _require_permission(principal, "usability.drafts.read")
    return _ok(await service.get_user_draft(session, principal.user.id, draft_id), request)


@router.post("/usability/drafts")
async def save_user_draft(
    payload: DraftSave,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    _require_permission(principal, "usability.drafts.write")
    return _ok(await service.save_draft(session, principal.user.id, payload), request)


@router.delete("/usability/drafts/{draft_id}")
async def discard_user_draft(
    draft_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    _require_permission(principal, "usability.drafts.discard")
    return _ok(await service.discard_draft(session, principal.user.id, draft_id), request)


@router.post("/usability/imports/preview")
async def preview_user_import(
    payload: ImportPreview,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    _require_permission(principal, "usability.imports.preview")
    return _ok(await service.preview_import(session, principal.user.id, payload), request)
