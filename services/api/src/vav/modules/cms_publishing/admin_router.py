"""Administrative content publishing API (B19 part 2).

Every route is permission-gated server-side. Hiding a button in the admin UI is
never the control (AUTH-002); the checks below are.

Authoring and publishing are separate permissions: an editor who can write a
draft cannot put it in front of members without ``cms.entries.publish``.
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
from vav.modules.cms_publishing import service
from vav.modules.cms_publishing.schemas import (
    ContentEntryCreateRequest,
    ContentEntryUpdateRequest,
    ContentRollbackRequest,
    ContentTransitionRequest,
    PreviewGrantRequest,
    SanitizePreviewRequest,
)
from vav.modules.identity.dependencies import AuthenticatedPrincipal
from vav.modules.identity.permissions import require_permission

router = APIRouter(prefix="/admin")


@router.post("/content/entries")
async def create_entry(
    payload: ContentEntryCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("cms.entries.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_entry(
            session, actor_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


@router.put("/content/entries/{entry_id}")
async def update_entry(
    entry_id: UUID,
    payload: ContentEntryUpdateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("cms.entries.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Replace the locale bodies. The response reports what the sanitizer removed."""

    return success(
        await service.update_entry(
            session, entry_id=entry_id, actor_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


@router.post("/content/entries/{entry_id}/transitions")
async def transition_entry(
    entry_id: UUID,
    payload: ContentTransitionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("cms.entries.publish")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.transition_entry(
            session, entry_id=entry_id, actor_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


@router.get("/content/entries/{entry_id}/revisions")
async def list_revisions(
    entry_id: UUID,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("cms.revisions.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.list_revisions(session, entry_id=entry_id),
        request_id_from_request(request),
    )


@router.post("/content/entries/{entry_id}/rollbacks")
async def rollback_entry(
    entry_id: UUID,
    payload: ContentRollbackRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("cms.revisions.rollback")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Restore an older revision. History is appended to, never rewritten."""

    return success(
        await service.rollback_entry(
            session, entry_id=entry_id, actor_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


@router.post("/content/entries/{entry_id}/previews")
async def grant_preview(
    entry_id: UUID,
    payload: PreviewGrantRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("cms.previews.grant")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.grant_preview(
            session, entry_id=entry_id, actor_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


@router.delete("/content/previews/{grant_id}")
async def revoke_preview(
    grant_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("cms.previews.grant")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.revoke_preview(session, grant_id=grant_id, actor_id=principal.user.id),
        request_id_from_request(request),
    )


@router.post("/content/sanitize-preview")
async def sanitize_preview(
    payload: SanitizePreviewRequest,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("cms.entries.manage")),
) -> dict[str, Any]:
    """Dry-run the sanitizer so an editor sees what will be stripped, before saving."""

    return success(
        service.preview_sanitizer(payload.model_dump()), request_id_from_request(request)
    )


@router.get("/content/translation-coverage")
async def translation_coverage(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("cms.entries.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """The fallback backlog: which published entries are missing which locales."""

    return success(await service.translation_coverage(session), request_id_from_request(request))


@router.get("/content/entries")
async def list_entries(
    request: Request,
    content_type: str | None = Query(default=None, max_length=64),
    locale: str = Query(default="zh-CN", max_length=16),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _principal: AuthenticatedPrincipal = Depends(require_permission("cms.entries.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.list_public_entries(
            session, content_type=content_type, locale=locale, limit=limit, offset=offset
        ),
        request_id_from_request(request),
    )
