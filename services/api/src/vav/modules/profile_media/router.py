"""Member-facing profile media API (PROFILE-001).

Private media is never addressed by asset id in a public URL: every response
carries an opaque token path. The API authorizes the viewer before issuing a
short-lived S3 bearer URL; storage URLs themselves are transferable during that
TTL and are not described as viewer-bound. Upload limits and content inspection
are enforced by the service, not by the client.
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
from vav.modules.identity.abuse import enforce_rate_limit
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

    await enforce_rate_limit(
        f"rate:profile-media:upload:{principal.user.id}", limit=12, window_seconds=3600
    )

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

    # Finalization downloads and fully decodes up to 100 MB.  Share the owner's
    # upload budget and also cap retries for one asset so a permanently invalid
    # object cannot be used as an unbounded CPU/memory endpoint.
    await enforce_rate_limit(
        f"rate:profile-media:upload:{principal.user.id}", limit=12, window_seconds=3600
    )
    await enforce_rate_limit(
        f"rate:profile-media:finalize:{asset_id}", limit=4, window_seconds=3600
    )

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
    await enforce_rate_limit(
        f"rate:profile-media:upload:{principal.user.id}", limit=12, window_seconds=3600
    )
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
    """Authorize this viewer and mint a short-lived bearer URL."""

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
