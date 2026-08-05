"""Operational relationship views and safety controls.

No route here can accept a proposal, confirm a relationship, resume a journey,
or restore an ended journey on behalf of either participant.
"""

# ruff: noqa: B008, E501

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.exceptions import VavError
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.identity.dependencies import AuthenticatedPrincipal
from vav.modules.identity.permissions import require_permission
from vav.modules.relationships import service
from vav.modules.relationships.schemas import AdminSafetyRequest

router = APIRouter(prefix="/admin/relationships")


def _anonymous(user_id: UUID) -> str:
    return f"user-{str(user_id)[:8]}"


@router.get("/dashboard")
async def dashboard(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(
        require_permission("relationships.analytics.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT count(*) AS total,count(*) FILTER (WHERE status='active') AS active,count(*) FILTER (WHERE status='paused') AS paused,count(*) FILTER (WHERE status='safety_frozen') AS safety_frozen,count(*) FILTER (WHERE status='ended') AS ended,(SELECT count(*) FROM relationship_stage_proposals WHERE status='pending') AS pending_proposals,(SELECT count(*) FROM relationship_dead_letters WHERE status='open') AS dead_letters FROM relationship_journeys"
                )
            )
        )
        .mappings()
        .one()
    )
    return success(
        {
            **{key: int(value or 0) for key, value in row.items()},
            "note": "Process metrics only. They do not measure relationship quality, health, or success.",
        },
        request_id_from_request(request),
    )


@router.get("")
async def journeys(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("relationships.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            text(
                "SELECT id,journey_number,user_low_id,user_high_id,status,current_stage_code,started_at,paused_at,ended_at,version,updated_at FROM relationship_journeys ORDER BY updated_at DESC LIMIT 300"
            )
        )
    ).mappings()
    return success(
        [
            {
                "journey_id": str(row["id"]),
                "journey_number": row["journey_number"],
                "members": [_anonymous(row["user_low_id"]), _anonymous(row["user_high_id"])],
                "status": row["status"],
                "current_stage_code": row["current_stage_code"],
                "started_at": row["started_at"],
                "paused_at": row["paused_at"],
                "ended_at": row["ended_at"],
                "version": row["version"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ],
        request_id_from_request(request),
    )


@router.get("/{journey_id}")
async def journey(
    journey_id: UUID,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_permission("relationships.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,journey_number,user_low_id,user_high_id,status,current_stage_code,stage_registry_version,policy_version,started_at,paused_at,ended_at,version FROM relationship_journeys WHERE id=:id"
                ),
                {"id": journey_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError(
            "RELATIONSHIP_NOT_FOUND", "That relationship journey was not found.", status_code=404
        )
    timeline_rows = (
        await session.execute(
            text(
                "SELECT event_type,from_status,to_status,from_stage_code,to_stage_code,reason_code,occurred_at FROM relationship_status_history WHERE journey_id=:id ORDER BY occurred_at"
            ),
            {"id": journey_id},
        )
    ).mappings()
    return success(
        {
            "journey_id": str(row["id"]),
            "journey_number": row["journey_number"],
            "members": [_anonymous(row["user_low_id"]), _anonymous(row["user_high_id"])],
            "status": row["status"],
            "current_stage_code": row["current_stage_code"],
            "stage_registry_version": row["stage_registry_version"],
            "policy_version": row["policy_version"],
            "started_at": row["started_at"],
            "paused_at": row["paused_at"],
            "ended_at": row["ended_at"],
            "version": row["version"],
            "timeline": [dict(item) for item in timeline_rows],
            "private_content_excluded": True,
        },
        request_id_from_request(request),
    )


@router.post("/{journey_id}/freeze")
async def freeze(
    journey_id: UUID,
    payload: AdminSafetyRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("relationships.freeze")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.safety_transition(
            session,
            journey_id=journey_id,
            actor_id=principal.user.id,
            freeze=True,
            reason_code=payload.reason_code,
            purpose=payload.purpose,
        ),
        request_id_from_request(request),
    )


@router.post("/{journey_id}/unfreeze")
async def unfreeze(
    journey_id: UUID,
    payload: AdminSafetyRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("relationships.unfreeze")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.safety_transition(
            session,
            journey_id=journey_id,
            actor_id=principal.user.id,
            freeze=False,
            reason_code=payload.reason_code,
            purpose=payload.purpose,
        ),
        request_id_from_request(request),
    )


@router.post("/{journey_id}/end-for-safety")
async def safety_end(
    journey_id: UUID,
    payload: AdminSafetyRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("relationships.end_for_safety")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.end_journey(
            session,
            journey_id=journey_id,
            actor_id=principal.user.id,
            confirmed=True,
            reason_code=payload.reason_code,
            private_reason=None,
            visible_message=None,
            ending_type="safety_ended",
            authorize_participant=False,
        ),
        request_id_from_request(request),
    )
