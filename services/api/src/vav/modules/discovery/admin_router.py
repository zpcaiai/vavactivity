"""Administrative discovery API (GEO-001 / MAP-001 / SHARE-001).

Every route is permission-gated server-side. Hiding a button in the admin UI is
never the control (AUTH-002); the checks below are.

New permission codes required by this module - add these to
``vav/modules/identity/permissions.py`` (they are deliberately NOT inserted by
the migration, because ``permissions`` has NOT NULL ``resource`` / ``action`` /
``risk_level`` columns that only the permission registry knows how to fill):

* ``discovery.venue_location.manage``  - geocode and store an activity venue
* ``discovery.map_provider.manage``    - pin a country to a map provider
* ``discovery.location.read``          - inspect how a member's city resolved
* ``activities.share.manage``          - generate or refresh a share card/link
* ``activities.share.revoke``          - revoke live share links for an activity
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
from vav.modules.discovery import service
from vav.modules.discovery.schemas import (
    GeocodeRequest,
    MapProviderConfigRequest,
    ShareCardRequest,
    ShareRevokeRequest,
    VenueLocationRequest,
)
from vav.modules.identity.dependencies import AuthenticatedPrincipal
from vav.modules.identity.permissions import require_permission

router = APIRouter(prefix="/admin/discovery")


# --- MAP-001 geocoding and venue locations ----------------------------------


@router.post("/geocode")
async def geocode_preview(
    payload: GeocodeRequest,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(
        require_permission("discovery.venue_location.manage")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Preview a geocode. A failure returns the manual address, never a 5xx."""

    return success(
        await service.geocode_preview(session, payload=payload.model_dump()),
        request_id_from_request(request),
    )


@router.put("/venue-locations")
async def save_venue_location(
    payload: VenueLocationRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("discovery.venue_location.manage")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.save_venue_location(
            session, actor_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


@router.get("/activities/{activity_id}/venue-location")
async def venue_location(
    activity_id: UUID,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(
        require_permission("discovery.venue_location.manage")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_venue_location(session, activity_id),
        request_id_from_request(request),
    )


@router.get("/map-providers")
async def list_map_providers(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(
        require_permission("discovery.map_provider.manage")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        {"items": await service.list_map_provider_configs(session)},
        request_id_from_request(request),
    )


@router.put("/map-providers")
async def set_map_provider(
    payload: MapProviderConfigRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("discovery.map_provider.manage")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.upsert_map_provider_config(
            session, actor_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )


# --- GEO-001 support tooling -------------------------------------------------


@router.get("/members/{user_id}/location")
async def member_location(
    user_id: UUID,
    request: Request,
    ip_city_code: str | None = Query(default=None, max_length=32),
    _principal: AuthenticatedPrincipal = Depends(require_permission("discovery.location.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Explain how a member's city resolved. Returns codes, never an IP."""

    return success(
        await service.location_debug(session, user_id=user_id, ip_city_code=ip_city_code),
        request_id_from_request(request),
    )


# --- SHARE-001 share cards and links ----------------------------------------


@router.post("/activities/{activity_id}/share-card")
async def create_share_card(
    activity_id: UUID,
    payload: ShareCardRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.share.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.create_share_card(
            session,
            activity_id=activity_id,
            actor_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


@router.post("/activities/{activity_id}/share-links/revoke")
async def revoke_share_links(
    activity_id: UUID,
    payload: ShareRevokeRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.share.revoke")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.revoke_share_links(
            session,
            activity_id=activity_id,
            actor_id=principal.user.id,
            reason=payload.reason,
        ),
        request_id_from_request(request),
    )
