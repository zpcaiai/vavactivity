"""Member-facing profile media API (PROFILE-001).

Private media is never addressed by asset id in a public URL: every response
carries an opaque token path, and fetching the bytes additionally requires a
short-lived signed grant bound to the viewer. Upload limits are enforced by the
service, not by the client.
"""

# ruff: noqa: B008, E501

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_authenticated_user
from vav.modules.profile_media import service
from vav.modules.profile_media.schemas import (
    MediaAccessRequest,
    MediaFinalizeRequest,
    MediaReplaceRequest,
    MediaUploadRequest,
    ProfileTagsRequest,
    ShareConsentRequest,
)

router = APIRouter(prefix="/account/profile-media")


@router.get("")
async def my_media(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_my_media(session, owner_id=principal.user.id),
        request_id_from_request(request),
    )


@router.post("/uploads")
async def register_upload(
    payload: MediaUploadRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Register an upload slot. Count, size, duration and mime are checked here."""

    return success(
        await service.register_upload(
            session, owner_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


@router.post("/assets/{asset_id}/finalize")
async def finalize_upload(
    asset_id: UUID,
    payload: MediaFinalizeRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Confirm an upload with server-measured values; limits are re-checked."""

    return success(
        await service.finalize_upload(
            session,
            owner_id=principal.user.id,
            asset_id=asset_id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


@router.put("/assets/{asset_id}")
async def replace_asset(
    asset_id: UUID,
    payload: MediaReplaceRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.replace_asset(
            session,
            owner_id=principal.user.id,
            asset_id=asset_id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


@router.delete("/assets/{asset_id}")
async def delete_asset(
    asset_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.delete_asset(session, owner_id=principal.user.id, asset_id=asset_id),
        request_id_from_request(request),
    )


@router.post("/assets/{asset_id}/access-grants")
async def issue_access_grant(
    asset_id: UUID,
    payload: MediaAccessRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Mint a short-lived, viewer-bound grant for one private asset."""

    return success(
        await service.issue_media_grant(
            session,
            viewer_id=principal.user.id,
            asset_id=asset_id,
            ttl_seconds=payload.ttl_seconds,
        ),
        request_id_from_request(request),
    )


@router.put("/tags")
async def set_tags(
    payload: ProfileTagsRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.set_profile_tags(
            session, owner_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


@router.get("/share-consent")
async def share_consent(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_share_consent(session, principal.user.id),
        request_id_from_request(request),
    )


@router.put("/share-consent")
async def set_share_consent(
    payload: ShareConsentRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.set_share_consent(
            session, owner_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


@router.get("/share-card")
async def share_card(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """The consent-scoped share projection - approved and consented fields only."""

    return success(
        await service.get_share_card(session, owner_id=principal.user.id),
        request_id_from_request(request),
    )
