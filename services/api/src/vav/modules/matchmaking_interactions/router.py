"""Member-facing interaction API.

There is no endpoint anywhere in this file that returns who liked the current
member. That absence is the privacy guarantee — not a permission check that
could be misconfigured, but a route that does not exist.
"""

# ruff: noqa: B008, E501

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.identity.dependencies import AuthenticatedPrincipal, require_authenticated_user
from vav.modules.matchmaking_interactions import contact_exchange as exchange_service
from vav.modules.matchmaking_interactions import idempotency
from vav.modules.matchmaking_interactions import invitations as invitation_service
from vav.modules.matchmaking_interactions import likes as like_service
from vav.modules.matchmaking_interactions import matches as match_service
from vav.modules.matchmaking_interactions.idempotency import IdempotencyOperation
from vav.modules.matchmaking_interactions.schemas import (
    CloseMatchRequest,
    ContactConsentRequest,
    ContactRevealRequest,
    ContactRevealTokenRequest,
    DeclineInvitationRequest,
    InvitationDecisionRequest,
    InvitationRequest,
    SkipRequest,
)

router = APIRouter()


def _request_uuid(request: Request) -> UUID | None:
    raw = request_id_from_request(request)
    try:
        return UUID(raw)
    except (ValueError, AttributeError, TypeError):
        return None


async def _idempotent(
    session: AsyncSession,
    *,
    user_id: UUID,
    operation: str,
    key: str | None,
    payload: dict[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    """Claim the key or hand back the earlier response for the same request."""
    normalised = idempotency.normalise_key(key)
    replayed = await idempotency.begin(
        session, user_id=user_id, operation=operation, key=normalised, payload=payload
    )
    return normalised, replayed.payload if replayed is not None else None


@router.post("/recommendations/{recommendation_item_id}/like")
async def like_recommendation(
    recommendation_item_id: UUID,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    payload = {"recommendation_item_id": str(recommendation_item_id)}
    key, replayed = await _idempotent(
        session,
        user_id=principal.user.id,
        operation=IdempotencyOperation.LIKE,
        key=idempotency_key,
        payload=payload,
    )
    if replayed is not None:
        return success(replayed, request_id_from_request(request))
    result = await like_service.create_like(
        session,
        viewer_user_id=principal.user.id,
        recommendation_item_id=recommendation_item_id,
        idempotency_key=key,
        request_id=_request_uuid(request),
    )
    await idempotency.complete(
        session,
        user_id=principal.user.id,
        operation=IdempotencyOperation.LIKE,
        key=key,
        response=result,
    )
    return success(result, request_id_from_request(request))


@router.post("/recommendations/{recommendation_item_id}/skip")
async def skip_recommendation(
    recommendation_item_id: UUID,
    payload: SkipRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    body = {
        "recommendation_item_id": str(recommendation_item_id),
        "skip_type": payload.skip_type,
        "reason_code": payload.reason_code,
    }
    key, replayed = await _idempotent(
        session,
        user_id=principal.user.id,
        operation=IdempotencyOperation.SKIP,
        key=idempotency_key,
        payload=body,
    )
    if replayed is not None:
        return success(replayed, request_id_from_request(request))
    result = await like_service.create_skip(
        session,
        viewer_user_id=principal.user.id,
        recommendation_item_id=recommendation_item_id,
        skip_type=payload.skip_type,
        reason_code=payload.reason_code,
        reason_details=payload.reason_details,
        idempotency_key=key,
        request_id=_request_uuid(request),
    )
    await idempotency.complete(
        session,
        user_id=principal.user.id,
        operation=IdempotencyOperation.SKIP,
        key=key,
        response=result,
    )
    return success(result, request_id_from_request(request))


@router.get("/account/matchmaking/outgoing-likes")
async def list_outgoing_likes(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await like_service.outgoing_likes(session, principal.user.id),
        request_id_from_request(request),
    )


@router.get("/account/matchmaking/skips")
async def list_skips(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await like_service.own_skips(session, principal.user.id),
        request_id_from_request(request),
    )


@router.delete("/account/matchmaking/likes/{like_id}")
async def withdraw_like(
    like_id: UUID,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    key, replayed = await _idempotent(
        session,
        user_id=principal.user.id,
        operation=IdempotencyOperation.WITHDRAW_LIKE,
        key=idempotency_key,
        payload={"like_id": str(like_id)},
    )
    if replayed is not None:
        return success(replayed, request_id_from_request(request))
    result = await like_service.withdraw_like(
        session,
        viewer_user_id=principal.user.id,
        like_id=like_id,
        request_id=_request_uuid(request),
    )
    await idempotency.complete(
        session,
        user_id=principal.user.id,
        operation=IdempotencyOperation.WITHDRAW_LIKE,
        key=key,
        response=result,
    )
    return success(result, request_id_from_request(request))


@router.delete("/account/matchmaking/skips/{skip_id}")
async def withdraw_skip(
    skip_id: UUID,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    key, replayed = await _idempotent(
        session,
        user_id=principal.user.id,
        operation=IdempotencyOperation.WITHDRAW_SKIP,
        key=idempotency_key,
        payload={"skip_id": str(skip_id)},
    )
    if replayed is not None:
        return success(replayed, request_id_from_request(request))
    result = await like_service.withdraw_skip(
        session,
        viewer_user_id=principal.user.id,
        skip_id=skip_id,
        request_id=_request_uuid(request),
    )
    await idempotency.complete(
        session,
        user_id=principal.user.id,
        operation=IdempotencyOperation.WITHDRAW_SKIP,
        key=key,
        response=result,
    )
    return success(result, request_id_from_request(request))


# --------------------------------------------------------------------------
# Mutual matches
# --------------------------------------------------------------------------


def _match_dto(match: dict[str, Any], user_id: UUID) -> dict[str, Any]:
    """What a member sees about a match.

    Not included, deliberately: when the other member decided, how long they
    took, their preferences, or any internal score.
    """
    return {
        "mutual_match_id": str(match["id"]),
        "match_number": match["match_number"],
        "other_member_user_id": str(match_service.other_member(match, user_id)),
        "source": match["source"],
        "status": match["status"],
        "matched_at": match["matched_at"],
        "invitation_status": match.get("invitation_status"),
        "contact_exchange_status": match.get("contact_exchange_status"),
    }


@router.get("/account/matchmaking/mutual-matches")
async def list_mutual_matches(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    rows = await match_service.list_matches(session, principal.user.id)
    return success(
        [_match_dto(row, principal.user.id) for row in rows], request_id_from_request(request)
    )


@router.get("/account/matchmaking/mutual-matches/{match_id}")
async def get_mutual_match(
    match_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    match = await match_service.member_match(session, user_id=principal.user.id, match_id=match_id)
    return success(_match_dto(match, principal.user.id), request_id_from_request(request))


@router.post("/account/matchmaking/mutual-matches/{match_id}/close")
async def close_mutual_match(
    match_id: UUID,
    payload: CloseMatchRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    key, replayed = await _idempotent(
        session,
        user_id=principal.user.id,
        operation=IdempotencyOperation.CLOSE_MATCH,
        key=idempotency_key,
        payload={"match_id": str(match_id), "reason_code": payload.reason_code},
    )
    if replayed is not None:
        return success(replayed, request_id_from_request(request))
    result = await match_service.close_match(
        session,
        user_id=principal.user.id,
        match_id=match_id,
        reason_code=payload.reason_code,
        request_id=_request_uuid(request),
    )
    await idempotency.complete(
        session,
        user_id=principal.user.id,
        operation=IdempotencyOperation.CLOSE_MATCH,
        key=key,
        response=result,
    )
    return success(result, request_id_from_request(request))


# --------------------------------------------------------------------------
# Introductions
# --------------------------------------------------------------------------


@router.post("/account/matchmaking/mutual-matches/{match_id}/invitations")
async def send_invitation(
    match_id: UUID,
    payload: InvitationRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    key, replayed = await _idempotent(
        session,
        user_id=principal.user.id,
        operation=IdempotencyOperation.SEND_INVITATION,
        key=idempotency_key,
        payload={"match_id": str(match_id), "message": payload.message},
    )
    if replayed is not None:
        return success(replayed, request_id_from_request(request))
    result = await invitation_service.send_invitation(
        session,
        sender_user_id=principal.user.id,
        match_id=match_id,
        message=payload.message,
        idempotency_key=key,
        request_id=_request_uuid(request),
    )
    await idempotency.complete(
        session,
        user_id=principal.user.id,
        operation=IdempotencyOperation.SEND_INVITATION,
        key=key,
        response=result,
    )
    return success(result, request_id_from_request(request))


@router.get("/account/matchmaking/invitations")
async def list_invitations(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await invitation_service.list_invitations(session, principal.user.id),
        request_id_from_request(request),
    )


@router.get("/account/matchmaking/invitations/{invitation_id}")
async def get_invitation(
    invitation_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await invitation_service.get_invitation(
            session, user_id=principal.user.id, invitation_id=invitation_id
        ),
        request_id_from_request(request),
    )


@router.post("/account/matchmaking/invitations/{invitation_id}/accept")
async def accept_invitation(
    invitation_id: UUID,
    payload: InvitationDecisionRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    key, replayed = await _idempotent(
        session,
        user_id=principal.user.id,
        operation=IdempotencyOperation.ACCEPT_INVITATION,
        key=idempotency_key,
        payload={
            "invitation_id": str(invitation_id),
            "expected_invitation_version": payload.expected_invitation_version,
        },
    )
    if replayed is not None:
        return success(replayed, request_id_from_request(request))
    result = await invitation_service.accept_invitation(
        session,
        user_id=principal.user.id,
        invitation_id=invitation_id,
        expected_invitation_version=payload.expected_invitation_version,
        request_id=_request_uuid(request),
    )
    await idempotency.complete(
        session,
        user_id=principal.user.id,
        operation=IdempotencyOperation.ACCEPT_INVITATION,
        key=key,
        response=result,
    )
    return success(result, request_id_from_request(request))


@router.post("/account/matchmaking/invitations/{invitation_id}/decline")
async def decline_invitation(
    invitation_id: UUID,
    payload: DeclineInvitationRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    key, replayed = await _idempotent(
        session,
        user_id=principal.user.id,
        operation=IdempotencyOperation.DECLINE_INVITATION,
        key=idempotency_key,
        payload={
            "invitation_id": str(invitation_id),
            "reason_code": payload.reason_code,
            "expected_invitation_version": payload.expected_invitation_version,
        },
    )
    if replayed is not None:
        return success(replayed, request_id_from_request(request))
    result = await invitation_service.decline_invitation(
        session,
        user_id=principal.user.id,
        invitation_id=invitation_id,
        reason_code=payload.reason_code,
        expected_invitation_version=payload.expected_invitation_version,
        request_id=_request_uuid(request),
    )
    await idempotency.complete(
        session,
        user_id=principal.user.id,
        operation=IdempotencyOperation.DECLINE_INVITATION,
        key=key,
        response=result,
    )
    return success(result, request_id_from_request(request))


@router.post("/account/matchmaking/invitations/{invitation_id}/cancel")
async def cancel_invitation(
    invitation_id: UUID,
    payload: InvitationDecisionRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    key, replayed = await _idempotent(
        session,
        user_id=principal.user.id,
        operation=IdempotencyOperation.CANCEL_INVITATION,
        key=idempotency_key,
        payload={
            "invitation_id": str(invitation_id),
            "expected_invitation_version": payload.expected_invitation_version,
        },
    )
    if replayed is not None:
        return success(replayed, request_id_from_request(request))
    result = await invitation_service.cancel_invitation(
        session,
        user_id=principal.user.id,
        invitation_id=invitation_id,
        expected_invitation_version=payload.expected_invitation_version,
        request_id=_request_uuid(request),
    )
    await idempotency.complete(
        session,
        user_id=principal.user.id,
        operation=IdempotencyOperation.CANCEL_INVITATION,
        key=key,
        response=result,
    )
    return success(result, request_id_from_request(request))


# --------------------------------------------------------------------------
# Contact exchange
# --------------------------------------------------------------------------


@router.post("/account/matchmaking/mutual-matches/{match_id}/contact-exchange")
async def request_contact_exchange(
    match_id: UUID,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    key, replayed = await _idempotent(
        session,
        user_id=principal.user.id,
        operation=IdempotencyOperation.REQUEST_CONTACT_EXCHANGE,
        key=idempotency_key,
        payload={"match_id": str(match_id)},
    )
    if replayed is not None:
        return success(replayed, request_id_from_request(request))
    result = await exchange_service.request_exchange(
        session,
        user_id=principal.user.id,
        match_id=match_id,
        request_id=_request_uuid(request),
    )
    await idempotency.complete(
        session,
        user_id=principal.user.id,
        operation=IdempotencyOperation.REQUEST_CONTACT_EXCHANGE,
        key=key,
        response=result,
    )
    return success(result, request_id_from_request(request))


@router.get("/account/matchmaking/contact-exchanges/{exchange_id}")
async def get_contact_exchange(
    exchange_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await exchange_service.get_exchange(
            session, user_id=principal.user.id, exchange_id=exchange_id
        ),
        request_id_from_request(request),
    )


@router.post("/account/matchmaking/contact-exchanges/{exchange_id}/consent")
async def submit_contact_consent(
    exchange_id: UUID,
    payload: ContactConsentRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    key, replayed = await _idempotent(
        session,
        user_id=principal.user.id,
        operation=IdempotencyOperation.SUBMIT_CONTACT_CONSENT,
        key=idempotency_key,
        payload={
            "exchange_id": str(exchange_id),
            "selected": sorted(str(i) for i in payload.selected_contact_point_ids),
            "platform_only": payload.platform_only,
        },
    )
    if replayed is not None:
        return success(replayed, request_id_from_request(request))
    result = await exchange_service.submit_consent(
        session,
        user_id=principal.user.id,
        exchange_id=exchange_id,
        selected_contact_point_ids=payload.selected_contact_point_ids,
        platform_only=payload.platform_only,
        request_id=_request_uuid(request),
    )
    await idempotency.complete(
        session,
        user_id=principal.user.id,
        operation=IdempotencyOperation.SUBMIT_CONTACT_CONSENT,
        key=key,
        response=result,
    )
    return success(result, request_id_from_request(request))


@router.delete("/account/matchmaking/contact-exchanges/{exchange_id}/consent")
async def withdraw_contact_consent(
    exchange_id: UUID,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    key, replayed = await _idempotent(
        session,
        user_id=principal.user.id,
        operation=IdempotencyOperation.WITHDRAW_CONTACT_CONSENT,
        key=idempotency_key,
        payload={"exchange_id": str(exchange_id)},
    )
    if replayed is not None:
        return success(replayed, request_id_from_request(request))
    result = await exchange_service.withdraw_consent(
        session,
        user_id=principal.user.id,
        exchange_id=exchange_id,
        request_id=_request_uuid(request),
    )
    await idempotency.complete(
        session,
        user_id=principal.user.id,
        operation=IdempotencyOperation.WITHDRAW_CONTACT_CONSENT,
        key=key,
        response=result,
    )
    return success(result, request_id_from_request(request))


@router.post("/account/matchmaking/contact-exchanges/{exchange_id}/reveal-token")
async def issue_reveal_token(
    exchange_id: UUID,
    payload: ContactRevealTokenRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await exchange_service.issue_reveal_token(
            session,
            user_id=principal.user.id,
            exchange_id=exchange_id,
            contact_point_id=payload.contact_point_id,
            request_id=_request_uuid(request),
        ),
        request_id_from_request(request),
    )


@router.post("/account/matchmaking/contact-exchanges/{exchange_id}/reveal")
async def reveal_contact(
    exchange_id: UUID,
    payload: ContactRevealRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await exchange_service.reveal(
            session,
            user_id=principal.user.id,
            exchange_id=exchange_id,
            reveal_token=payload.reveal_token,
            request_id=_request_uuid(request),
        ),
        request_id_from_request(request),
    )
