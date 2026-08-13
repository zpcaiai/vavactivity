"""Onsite operator and administrative check-in API (CHK-002).

Every route is permission-gated server-side. Hiding a button in the operator UI
is never the control (AUTH-002); the checks below are.

Note the shape of the flow: ``lookup`` -> ``choices`` -> ``confirm``. Three
calls where one would "work", because the onsite failure mode is a tired
operator tapping a large button by accident, and a single-call check-in has no
step at which that mistake can be caught.
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
from vav.modules.checkin_operations import service
from vav.modules.checkin_operations.schemas import (
    ChoiceSelectRequest,
    ConfirmCheckinRequest,
    LastFourBackfillRequest,
    LastFourLookupRequest,
    RevokeCheckinRequest,
    UndoCheckinRequest,
    WindowPolicyRequest,
)
from vav.modules.identity.dependencies import AuthenticatedPrincipal
from vav.modules.identity.permissions import require_permission

router = APIRouter(prefix="/admin")


# --- lookup and disambiguation ---------------------------------------------


@router.post("/activities/{activity_id}/checkin/lookups")
async def lookup_by_last_four(
    activity_id: UUID,
    payload: LastFourLookupRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.checkin.operate")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Narrow the guest list by four digits.

    POST rather than GET on purpose: a four-digit fragment in a query string
    ends up in access logs, browser history and referrers, and this is the one
    input we have promised not to spread around.
    """

    return success(
        await service.lookup_by_last_four(
            session,
            activity_id=activity_id,
            operator_id=principal.user.id,
            payload=payload.model_dump(),
            request_id=request_id_from_request(request),
        ),
        request_id_from_request(request),
    )


@router.post("/checkin/choices")
async def select_candidate(
    payload: ChoiceSelectRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.checkin.operate")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Resolve one opaque choice token into a pending confirmation."""

    return success(
        await service.select_candidate(
            session,
            operator_id=principal.user.id,
            payload=payload.model_dump(),
            request_id=request_id_from_request(request),
        ),
        request_id_from_request(request),
    )


# --- check-in ---------------------------------------------------------------


@router.post("/checkin/confirmations")
async def confirm_checkin(
    payload: ConfirmCheckinRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.checkin.operate")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Write attendance. Idempotent: a repeat confirm is a success, not a 409."""

    return success(
        await service.confirm_checkin(
            session,
            operator_id=principal.user.id,
            payload=payload.model_dump(),
            request_id=request_id_from_request(request),
            has_window_override=False,
        ),
        request_id_from_request(request),
    )


@router.post("/checkin/confirmations/override")
async def confirm_checkin_with_override(
    payload: ConfirmCheckinRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("activities.checkin.override_window")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Check somebody in outside the permitted window.

    A separate route rather than a flag on the normal one, so the override
    permission is enforced by the router itself instead of by a conditional
    inside the service. ``override_reason`` is still mandatory: holding the
    permission answers "who may", not "why did they".
    """

    return success(
        await service.confirm_checkin(
            session,
            operator_id=principal.user.id,
            payload=payload.model_dump(),
            request_id=request_id_from_request(request),
            has_window_override=True,
        ),
        request_id_from_request(request),
    )


@router.post("/checkin/registrations/{registration_id}/undo")
async def undo_checkin(
    registration_id: UUID,
    payload: UndoCheckinRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.checkin.operate")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Undo a mis-tap inside the configured operator window, with a reason."""

    return success(
        await service.undo_checkin(
            session,
            registration_id=registration_id,
            operator_id=principal.user.id,
            payload=payload.model_dump(),
            request_id=request_id_from_request(request),
        ),
        request_id_from_request(request),
    )


@router.post("/checkin/registrations/{registration_id}/revocations")
async def revoke_checkin(
    registration_id: UUID,
    payload: RevokeCheckinRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("activities.checkin.revoke")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Administrative revocation after the undo window has closed."""

    return success(
        await service.revoke_checkin(
            session,
            registration_id=registration_id,
            actor_id=principal.user.id,
            payload=payload.model_dump(),
            request_id=request_id_from_request(request),
        ),
        request_id_from_request(request),
    )


# --- policy and audit -------------------------------------------------------


@router.put("/activities/{activity_id}/checkin/window-policy")
async def set_window_policy(
    activity_id: UUID,
    payload: WindowPolicyRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("activities.checkin.policy.manage")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.upsert_window_policy(
            session,
            activity_id=activity_id,
            actor_id=principal.user.id,
            payload=payload.model_dump(),
        ),
        request_id_from_request(request),
    )


@router.get("/activities/{activity_id}/checkin/window-policy")
async def read_window_policy(
    activity_id: UUID,
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(
        require_permission("activities.checkin.policy.manage")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.get_window_policy(session, activity_id), request_id_from_request(request)
    )


@router.get("/activities/{activity_id}/checkin/operations")
async def list_operations(
    activity_id: UUID,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    _principal: AuthenticatedPrincipal = Depends(
        require_permission("activities.checkin.audit.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """The operator-behaviour trail: lookups, duplicates, undos, refusals."""

    return success(
        {
            "items": await service.list_operation_events(
                session, activity_id=activity_id, limit=limit
            )
        },
        request_id_from_request(request),
    )


@router.get("/activities/{activity_id}/checkin/window-overrides")
async def list_window_overrides(
    activity_id: UUID,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    _principal: AuthenticatedPrincipal = Depends(
        require_permission("activities.checkin.audit.read")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Every out-of-window admission, with the reason its operator gave."""

    return success(
        {
            "items": await service.list_window_overrides(
                session, activity_id=activity_id, limit=limit
            )
        },
        request_id_from_request(request),
    )


@router.post("/checkin/last-four-backfill")
async def request_last_four_backfill(
    payload: LastFourBackfillRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("privacy.contact_points.backfill")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Queue the plaintext-touching job that populates ``last_four_hmac``.

    Its own high-risk permission because it is the one operation in this module
    that requires a worker to decrypt stored phone numbers in bulk.
    """

    return success(
        await service.request_last_four_backfill(
            session, actor_id=principal.user.id, payload=payload.model_dump()
        ),
        request_id_from_request(request),
    )
