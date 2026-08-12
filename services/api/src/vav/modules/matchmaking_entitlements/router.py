"""Member-facing matchmaking eligibility and entitlement API (B12).

Every route below runs the relationship gate before touching matchmaking data.
A non-single member receives 403 with no payload, not an empty list, so the
absence of data is not itself a signal.
"""

# ruff: noqa: B008, E501

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_authenticated_user
from vav.modules.matchmaking_entitlements import service
from vav.modules.matchmaking_entitlements.schemas import RelationshipStatusRequest

router = APIRouter(prefix="/account")


@router.get("/relationship-status")
async def relationship_status(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_relationship_status(session, principal.user.id),
        request_id_from_request(request),
    )


@router.put("/relationship-status")
async def set_relationship_status(
    payload: RelationshipStatusRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.set_relationship_status(
            session,
            user_id=principal.user.id,
            target=payload.status,
            source="self_declared",
            actor_id=principal.user.id,
            actor_kind="member",
            reason=payload.reason,
        ),
        request_id_from_request(request),
    )


@router.get("/matchmaking/entitlement")
async def entitlement(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_entitlement(session, principal.user.id),
        request_id_from_request(request),
    )


@router.post("/matchmaking/generations")
async def generate(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.generate_recommendations(session, user_id=principal.user.id),
        request_id_from_request(request),
    )


@router.get("/matchmaking/wait-pool")
async def wait_pool(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_wait_pool_state(session, principal.user.id),
        request_id_from_request(request),
    )
