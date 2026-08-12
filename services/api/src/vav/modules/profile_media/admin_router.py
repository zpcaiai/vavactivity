"""Administrative profile media API (PROFILE-001).

Every route is permission-gated server-side. Hiding a button in the admin UI is
never the control (AUTH-002); the checks below are.

New permission codes required by this module - add these to
``vav/modules/identity/permissions.py`` (they are deliberately NOT inserted by
the migration, because ``permissions`` has NOT NULL ``resource`` / ``action`` /
``risk_level`` columns that only the permission registry knows how to fill):

* ``profile_media.moderation.read``    - view the moderation queue
* ``profile_media.moderation.decide``  - approve / reject / re-queue an asset
* ``profile_media.assets.remove``      - operator takedown of an asset
* ``profile_media.assets.read``        - inspect one member's media state

Moderators receive the same opaque token paths members do; there is no
"raw storage URL" route, because that would be a permanent, unexpiring handle to
private media.
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
from vav.modules.profile_media import service
from vav.modules.profile_media.schemas import (
    AdminAssetRemovalRequest,
    ModerationDecisionRequest,
)

router = APIRouter(prefix="/admin/profile-media")


@router.get("/moderation-queue")
async def moderation_queue(
    request: Request,
    state: str = Query(default="pending", max_length=16),
    limit: int = Query(default=50, ge=1, le=200),
    _principal: AuthenticatedPrincipal = Depends(
        require_permission("profile_media.moderation.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        {"items": await service.moderation_queue(session, state=state, limit=limit)},
        request_id_from_request(request),
    )


@router.post("/assets/{asset_id}/moderation")
async def decide_moderation(
    asset_id: UUID,
    payload: ModerationDecisionRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("profile_media.moderation.decide")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.decide_moderation(
            session,
            asset_id=asset_id,
            actor_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


@router.post("/assets/remove")
async def remove_asset(
    payload: AdminAssetRemovalRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("profile_media.assets.remove")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.admin_remove_asset(
            session, actor_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


@router.get("/members/{user_id}")
async def member_media(
    user_id: UUID,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(
        require_permission("profile_media.assets.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_my_media(session, owner_id=user_id),
        request_id_from_request(request),
    )
