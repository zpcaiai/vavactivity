"""Member-facing check-in surface (CHK-002).

Deliberately tiny. A member can see whether *they* are checked in and how their
own credential stands; there is no member-facing route in this module that
searches, lists or resolves anybody. The operator surface lives entirely in
``admin_router`` behind permissions.
"""

# ruff: noqa: B008, E501

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.checkin_operations.service import checkin_operations_enabled
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_authenticated_user

router = APIRouter(prefix="/account")


@router.get("/activities/{activity_id}/checkin-status")
async def my_checkin_status(
    activity_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """The member's own attendance state for one activity.

    Scoped by ``user_id`` in the query itself rather than filtered after the
    fact, so a wrong ``activity_id`` returns nothing instead of somebody else's
    row.
    """

    checkin_operations_enabled()
    row = (
        (
            await session.execute(
                text(
                    "SELECT r.id, r.attendance_status, r.status,"
                    " (SELECT max(e.occurred_at) FROM activity_checkin_events e"
                    "    WHERE e.registration_id=r.id AND e.action='check_in') AS checked_in_at"
                    " FROM activity_registrations r"
                    " WHERE r.activity_id=:activity_id AND r.user_id=:user_id"
                ),
                {"activity_id": str(activity_id), "user_id": str(principal.user.id)},
            )
        )
        .mappings()
        .first()
    )
    payload: dict[str, Any] = {"activity_id": str(activity_id), "registered": row is not None}
    if row is not None:
        payload.update(
            {
                "registration_id": str(row["id"]),
                "registration_status": row["status"],
                "attendance_status": row["attendance_status"],
                "checked_in_at": row["checked_in_at"].isoformat() if row["checked_in_at"] else None,
            }
        )
    return success(payload, request_id_from_request(request))
