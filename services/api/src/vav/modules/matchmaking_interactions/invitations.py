"""Introduction invitations.

A mutual match says both members were interested. An invitation says one of
them is ready to start actually getting to know the other, and acceptance is
what hands the pair to Batch 16. Keeping these separate means a match never
silently becomes a relationship.
"""

# ruff: noqa: E501

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.matchmaking_interactions import matches as match_service
from vav.modules.matchmaking_interactions import service
from vav.modules.matchmaking_interactions.domain import (
    DECLINE_REASON_CODES,
    CooldownType,
    InvitationStatus,
    MutualMatchStatus,
    PairStatus,
    canonical_pair,
    invitation_number,
    screen_invitation_message,
)
from vav.modules.matchmaking_interactions.gateways import (
    EventGateway,
    OutboxEvent,
    RecommendationGateway,
)
from vav.modules.privacy.crypto import decrypt_private, encrypt_private


async def send_invitation(
    session: AsyncSession,
    *,
    sender_user_id: UUID,
    match_id: UUID,
    message: str | None,
    idempotency_key: str,
    request_id: UUID | None = None,
) -> dict[str, Any]:
    """Send the one pending invitation a match is allowed to have."""
    service.enabled()
    settings = get_settings()
    if not settings.matchmaking_invitation_enabled:
        raise VavError("INVITATIONS_DISABLED", "Introductions are not available.", status_code=503)

    match = await match_service.member_match(session, user_id=sender_user_id, match_id=match_id)
    await service.lock_pair(session, match["pair_id"])
    # Re-read under the lock: a concurrent decline or block may have moved the
    # match since the ownership check above.
    match = await match_service.member_match(session, user_id=sender_user_id, match_id=match_id)

    status = MutualMatchStatus(str(match["status"]))
    if status is MutualMatchStatus.INVITATION_PENDING:
        raise VavError(
            "INVITATION_ALREADY_PENDING",
            "An introduction is already waiting for a reply.",
            status_code=409,
        )
    if status is not MutualMatchStatus.ACTIVE:
        raise VavError(
            "MUTUAL_MATCH_NOT_ACTIVE",
            "This match is not open for an introduction.",
            status_code=409,
        )

    recipient_user_id = match_service.other_member(match, sender_user_id)
    eligibility = await service.check_interaction_allowed(
        session, actor_user_id=sender_user_id, target_user_id=recipient_user_id
    )
    eligibility.raise_for_member()

    await _ensure_no_active_cooldown(session, pair_id=match["pair_id"])

    screening: dict[str, Any] = {"checked": True, "violations": []}
    encrypted_message = None
    if message is not None and message.strip():
        body = message.strip()
        if len(body) > settings.matchmaking_invitation_message_max_chars:
            raise VavError(
                "INVITATION_MESSAGE_TOO_LONG",
                "Your message is longer than the limit.",
                status_code=422,
            )
        violations = screen_invitation_message(body)
        if violations and settings.matchmaking_invitation_contact_info_blocking:
            # Contact details belong in the exchange flow, where both members
            # decide separately and can revoke. Free text would bypass that.
            raise VavError(
                "INVITATION_MESSAGE_REJECTED",
                "Please remove contact details, links and payment requests from your message.",
                status_code=422,
                details=[{"violations": violations}],
            )
        screening["violations"] = violations
        encrypted_message = encrypt_private(body)

    expires_at = service.now() + timedelta(days=settings.matchmaking_invitation_ttl_days)
    try:
        inserted = (
            await session.execute(
                text(
                    "INSERT INTO matchmaking_introduction_invitations "
                    "(invitation_number,mutual_match_id,pair_id,sender_user_id,recipient_user_id,"
                    "status,message_encrypted,message_screening,policy_snapshot,idempotency_key,"
                    "expires_at) VALUES "
                    "(:number,:match,:pair,:sender,:recipient,:status,:message,"
                    "CAST(:screening AS jsonb),CAST(:policy AS jsonb),:key,:expires) RETURNING *"
                ),
                {
                    "number": invitation_number(),
                    "match": match_id,
                    "pair": match["pair_id"],
                    "sender": sender_user_id,
                    "recipient": recipient_user_id,
                    "status": InvitationStatus.PENDING.value,
                    "message": encrypted_message,
                    "screening": _json(screening),
                    "policy": _json(
                        {
                            "ttl_days": settings.matchmaking_invitation_ttl_days,
                            "contact_exchange_policy": settings.matchmaking_contact_exchange_policy,
                            "expired_reopens_match": settings.matchmaking_expired_invitation_reopens_match,
                        }
                    ),
                    "key": idempotency_key,
                    "expires": expires_at,
                },
            )
        ).mappings()
    except IntegrityError as exc:
        # The partial unique index is the real guarantee that a match has at
        # most one pending invitation.
        raise VavError(
            "INVITATION_ALREADY_PENDING",
            "An introduction is already waiting for a reply.",
            status_code=409,
        ) from exc
    invitation = dict(inserted.one())

    await _set_match_status(session, match_id, MutualMatchStatus.INVITATION_PENDING)
    await service.append_history(
        session,
        pair_id=match["pair_id"],
        entity_type="invitation",
        entity_id=invitation["id"],
        action="sent",
        actor_user_id=sender_user_id,
        to_status=InvitationStatus.PENDING.value,
        safe_metadata={"has_message": encrypted_message is not None},
        request_id=request_id,
    )
    await service.audit(
        session,
        event_type="matchmaking.invitation.sent",
        subject_type="invitation",
        subject_id=invitation["id"],
        actor_id=sender_user_id,
    )
    await EventGateway(session).publish(
        OutboxEvent(
            topic="matchmaking.introduction.sent",
            aggregate_type="matchmaking_invitation",
            aggregate_id=invitation["id"],
            payload={
                "invitation_id": str(invitation["id"]),
                "mutual_match_id": str(match_id),
                "recipient_user_ids": [str(recipient_user_id)],
                "expires_at": expires_at.isoformat(),
            },
        )
    )
    return _sender_view(invitation)


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=str)


async def _ensure_no_active_cooldown(session: AsyncSession, *, pair_id: UUID) -> None:
    rows = (
        await session.execute(
            text(
                "SELECT cooldown_type, expires_at FROM matchmaking_pair_cooldowns "
                "WHERE pair_id=:pair AND released_at IS NULL AND expires_at > now()"
            ),
            {"pair": pair_id},
        )
    ).mappings()
    active = rows.first()
    if active is not None:
        raise VavError(
            "INVITATION_COOLDOWN_ACTIVE",
            "You cannot send another introduction to this member yet.",
            status_code=409,
            details=[{"available_from": active["expires_at"]}],
        )


async def _set_match_status(
    session: AsyncSession, match_id: UUID, status: MutualMatchStatus
) -> None:
    await session.execute(
        text(
            "UPDATE matchmaking_mutual_matches SET status=:status, "
            "match_version=match_version+1, updated_at=now() WHERE id=:id"
        ),
        {"id": match_id, "status": status.value},
    )


async def _start_cooldown(
    session: AsyncSession,
    *,
    pair_id: UUID,
    cooldown_type: CooldownType,
    days: int,
    reason_code: str,
) -> None:
    await session.execute(
        text(
            "INSERT INTO matchmaking_pair_cooldowns "
            "(pair_id,cooldown_type,reason_code,expires_at) VALUES "
            "(:pair,:type,:reason,now() + make_interval(days => :days)) "
            "ON CONFLICT DO NOTHING"
        ),
        {"pair": pair_id, "type": cooldown_type.value, "reason": reason_code, "days": days},
    )


async def _locked_invitation(session: AsyncSession, invitation_id: UUID) -> dict[str, Any]:
    rows = (
        await session.execute(
            text("SELECT * FROM matchmaking_introduction_invitations WHERE id=:id FOR UPDATE"),
            {"id": invitation_id},
        )
    ).mappings()
    found = rows.first()
    if found is None:
        raise VavError("INVITATION_NOT_FOUND", "That introduction was not found.", status_code=404)
    return dict(found)


def _require_pending(invitation: dict[str, Any], *, expected_version: int | None) -> None:
    """Reject a stale write.

    Accept/cancel and accept/expire both land here. Whoever takes the row lock
    first wins; the second caller sees a status that is no longer ``pending``
    and is told the state moved rather than being allowed to overwrite it.
    """
    if str(invitation["status"]) != InvitationStatus.PENDING.value:
        raise VavError(
            "INVITATION_STATE_CHANGED",
            "This introduction is no longer waiting for a reply.",
            status_code=409,
            details=[{"status": invitation["status"]}],
        )
    if expected_version is not None and int(invitation["invitation_version"]) != expected_version:
        raise VavError(
            "INVITATION_STATE_CHANGED",
            "This introduction changed while you were reading it.",
            status_code=409,
            details=[{"status": invitation["status"]}],
        )


async def accept_invitation(
    session: AsyncSession,
    *,
    user_id: UUID,
    invitation_id: UUID,
    expected_invitation_version: int | None = None,
    request_id: UUID | None = None,
) -> dict[str, Any]:
    """Accept and hand the pair to Batch 16 exactly once."""
    service.enabled()
    invitation = await _locked_invitation(session, invitation_id)
    if invitation["recipient_user_id"] != user_id:
        # Only the recipient can accept. The sender accepting their own
        # invitation would manufacture a relationship out of one person.
        raise VavError("INVITATION_NOT_FOUND", "That introduction was not found.", status_code=404)
    _require_pending(invitation, expected_version=expected_invitation_version)

    if invitation["expires_at"] <= service.now():
        await _expire_locked(session, invitation)
        raise VavError(
            "INVITATION_STATE_CHANGED",
            "This introduction has expired.",
            status_code=409,
            details=[{"status": InvitationStatus.EXPIRED.value}],
        )

    eligibility = await service.check_interaction_allowed(
        session,
        actor_user_id=user_id,
        target_user_id=invitation["sender_user_id"],
    )
    eligibility.raise_for_member()

    handoff_id = uuid4()
    updated = (
        await session.execute(
            text(
                "UPDATE matchmaking_introduction_invitations SET status=:status, "
                "accepted_at=now(), relationship_handoff_id=:handoff, "
                "invitation_version=invitation_version+1, updated_at=now() "
                "WHERE id=:id AND status='pending' RETURNING *"
            ),
            {"id": invitation_id, "status": InvitationStatus.ACCEPTED.value, "handoff": handoff_id},
        )
    ).mappings()
    accepted = updated.first()
    if accepted is None:  # pragma: no cover - the row lock makes this unreachable
        raise VavError(
            "INVITATION_STATE_CHANGED", "This introduction is no longer pending.", status_code=409
        )

    await _set_match_status(
        session, invitation["mutual_match_id"], MutualMatchStatus.INTRODUCTION_ACCEPTED
    )
    low, high = canonical_pair(user_id, invitation["sender_user_id"])
    await RecommendationGateway(session).exclude_pair(
        user_low_id=low,
        user_high_id=high,
        exclusion_type="relationship",
        reason_code="relationship_started",
        expires_at=None,
    )
    await service.append_history(
        session,
        pair_id=invitation["pair_id"],
        entity_type="invitation",
        entity_id=invitation_id,
        action="accepted",
        actor_user_id=user_id,
        from_status=InvitationStatus.PENDING.value,
        to_status=InvitationStatus.ACCEPTED.value,
        request_id=request_id,
    )
    await service.audit(
        session,
        event_type="matchmaking.invitation.accepted",
        subject_type="invitation",
        subject_id=invitation_id,
        actor_id=user_id,
    )
    events = EventGateway(session)
    await events.publish(
        OutboxEvent(
            topic="matchmaking.introduction.accepted",
            aggregate_type="matchmaking_invitation",
            aggregate_id=invitation_id,
            payload={
                "invitation_id": str(invitation_id),
                "recipient_user_ids": [str(invitation["sender_user_id"])],
            },
        )
    )
    # One handoff, emitted inside the same transaction that flipped the status,
    # so a retry cannot produce a second relationship.
    await events.publish(
        OutboxEvent(
            topic="matchmaking.relationship_handoff.created",
            aggregate_type="matchmaking_relationship_handoff",
            aggregate_id=handoff_id,
            payload={
                "relationship_handoff_id": str(handoff_id),
                "mutual_match_id": str(invitation["mutual_match_id"]),
                "invitation_id": str(invitation_id),
                "user_low_id": str(low),
                "user_high_id": str(high),
            },
        )
    )
    return {
        "invitation_id": str(invitation_id),
        "status": InvitationStatus.ACCEPTED.value,
        "relationship_handoff_id": str(handoff_id),
    }


async def decline_invitation(
    session: AsyncSession,
    *,
    user_id: UUID,
    invitation_id: UUID,
    reason_code: str | None = None,
    expected_invitation_version: int | None = None,
    request_id: UUID | None = None,
) -> dict[str, Any]:
    """Decline. The reason is stored for safety review and never returned."""
    service.enabled()
    if reason_code is not None and reason_code not in DECLINE_REASON_CODES:
        raise VavError("DECLINE_REASON_INVALID", "That reason is not supported.", status_code=422)
    invitation = await _locked_invitation(session, invitation_id)
    if invitation["recipient_user_id"] != user_id:
        raise VavError("INVITATION_NOT_FOUND", "That introduction was not found.", status_code=404)
    _require_pending(invitation, expected_version=expected_invitation_version)

    await session.execute(
        text(
            "UPDATE matchmaking_introduction_invitations SET status=:status, declined_at=now(), "
            "decline_reason_code=:reason, invitation_version=invitation_version+1, "
            "updated_at=now() WHERE id=:id AND status='pending'"
        ),
        {"id": invitation_id, "status": InvitationStatus.DECLINED.value, "reason": reason_code},
    )
    await _close_match_after_decline(session, invitation, user_id=user_id)
    await service.append_history(
        session,
        pair_id=invitation["pair_id"],
        entity_type="invitation",
        entity_id=invitation_id,
        action="declined",
        actor_user_id=user_id,
        from_status=InvitationStatus.PENDING.value,
        to_status=InvitationStatus.DECLINED.value,
        # The reason code stays out of the timeline; it lives on the row and
        # behind the sensitive-read permission.
        request_id=request_id,
    )
    await service.audit(
        session,
        event_type="matchmaking.invitation.declined",
        subject_type="invitation",
        subject_id=invitation_id,
        actor_id=user_id,
    )
    await EventGateway(session).publish(
        OutboxEvent(
            topic="matchmaking.introduction.declined",
            aggregate_type="matchmaking_invitation",
            aggregate_id=invitation_id,
            payload={
                "invitation_id": str(invitation_id),
                "recipient_user_ids": [str(invitation["sender_user_id"])],
                # Deliberately no reason: the sender is told only that the
                # other member did not continue.
                "disclosure": "generic_status_only",
            },
        )
    )
    return {"invitation_id": str(invitation_id), "status": InvitationStatus.DECLINED.value}


async def _close_match_after_decline(
    session: AsyncSession, invitation: dict[str, Any], *, user_id: UUID
) -> None:
    settings = get_settings()
    await session.execute(
        text(
            "UPDATE matchmaking_mutual_matches SET status=:status, closed_at=now(), "
            "closure_reason_code='introduction_declined', match_version=match_version+1, "
            "updated_at=now() WHERE id=:id"
        ),
        {"id": invitation["mutual_match_id"], "status": MutualMatchStatus.CLOSED.value},
    )
    await service.clear_active_match(session, invitation["pair_id"])
    await service.touch_pair(session, invitation["pair_id"], status=PairStatus.CLOSED)
    await _start_cooldown(
        session,
        pair_id=invitation["pair_id"],
        cooldown_type=CooldownType.INVITATION_DECLINED,
        days=settings.matchmaking_declined_pair_cooldown_days,
        reason_code="introduction_declined",
    )
    low, high = canonical_pair(user_id, invitation["sender_user_id"])
    await RecommendationGateway(session).exclude_pair(
        user_low_id=low,
        user_high_id=high,
        exclusion_type=CooldownType.INVITATION_DECLINED.value,
        reason_code="introduction_declined",
        expires_at=service.now() + timedelta(days=settings.matchmaking_declined_pair_cooldown_days),
    )


async def cancel_invitation(
    session: AsyncSession,
    *,
    user_id: UUID,
    invitation_id: UUID,
    expected_invitation_version: int | None = None,
    request_id: UUID | None = None,
) -> dict[str, Any]:
    """The sender withdraws before a reply."""
    service.enabled()
    invitation = await _locked_invitation(session, invitation_id)
    if invitation["sender_user_id"] != user_id:
        raise VavError("INVITATION_NOT_FOUND", "That introduction was not found.", status_code=404)
    _require_pending(invitation, expected_version=expected_invitation_version)

    await session.execute(
        text(
            "UPDATE matchmaking_introduction_invitations SET status=:status, cancelled_at=now(), "
            "invitation_version=invitation_version+1, updated_at=now() "
            "WHERE id=:id AND status='pending'"
        ),
        {"id": invitation_id, "status": InvitationStatus.CANCELLED.value},
    )
    await _set_match_status(session, invitation["mutual_match_id"], MutualMatchStatus.ACTIVE)
    await service.append_history(
        session,
        pair_id=invitation["pair_id"],
        entity_type="invitation",
        entity_id=invitation_id,
        action="cancelled",
        actor_user_id=user_id,
        from_status=InvitationStatus.PENDING.value,
        to_status=InvitationStatus.CANCELLED.value,
        request_id=request_id,
    )
    await service.audit(
        session,
        event_type="matchmaking.invitation.cancelled",
        subject_type="invitation",
        subject_id=invitation_id,
        actor_id=user_id,
    )
    await EventGateway(session).publish(
        OutboxEvent(
            topic="matchmaking.introduction.cancelled",
            aggregate_type="matchmaking_invitation",
            aggregate_id=invitation_id,
            payload={"invitation_id": str(invitation_id)},
        )
    )
    return {"invitation_id": str(invitation_id), "status": InvitationStatus.CANCELLED.value}


async def _expire_locked(session: AsyncSession, invitation: dict[str, Any]) -> bool:
    """Expire one already-locked pending invitation. Returns True if it moved."""
    settings = get_settings()
    updated = (
        await session.execute(
            text(
                "UPDATE matchmaking_introduction_invitations SET status=:status, "
                "expired_at=now(), invitation_version=invitation_version+1, updated_at=now() "
                "WHERE id=:id AND status='pending' RETURNING id"
            ),
            {"id": invitation["id"], "status": InvitationStatus.EXPIRED.value},
        )
    ).mappings()
    if updated.first() is None:
        return False

    next_status = (
        MutualMatchStatus.ACTIVE
        if settings.matchmaking_expired_invitation_reopens_match
        else MutualMatchStatus.CLOSED
    )
    await _set_match_status(session, invitation["mutual_match_id"], next_status)
    await _start_cooldown(
        session,
        pair_id=invitation["pair_id"],
        cooldown_type=CooldownType.INVITATION_EXPIRED,
        days=settings.matchmaking_expired_invitation_cooldown_days,
        reason_code="introduction_expired",
    )
    await service.append_history(
        session,
        pair_id=invitation["pair_id"],
        entity_type="invitation",
        entity_id=invitation["id"],
        action="expired",
        from_status=InvitationStatus.PENDING.value,
        to_status=InvitationStatus.EXPIRED.value,
    )
    await service.audit(
        session,
        event_type="matchmaking.invitation.expired",
        subject_type="invitation",
        subject_id=invitation["id"],
    )
    await EventGateway(session).publish(
        OutboxEvent(
            topic="matchmaking.introduction.expired",
            aggregate_type="matchmaking_invitation",
            aggregate_id=invitation["id"],
            payload={"invitation_id": str(invitation["id"])},
        )
    )
    return True


async def expire_due_invitations(session: AsyncSession, *, limit: int = 200) -> int:
    """Expiry worker.

    ``FOR UPDATE SKIP LOCKED`` means a concurrent accept holding the row is
    skipped rather than fought over, so an invitation is never both accepted
    and expired.
    """
    service.enabled()
    rows = (
        await session.execute(
            text(
                "SELECT * FROM matchmaking_introduction_invitations "
                "WHERE status='pending' AND expires_at <= now() "
                "ORDER BY expires_at LIMIT :limit FOR UPDATE SKIP LOCKED"
            ),
            {"limit": limit},
        )
    ).mappings()
    expired = 0
    for row in rows:
        if await _expire_locked(session, dict(row)):
            expired += 1
    return expired


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------


def _sender_view(invitation: dict[str, Any]) -> dict[str, Any]:
    return {
        "invitation_id": str(invitation["id"]),
        "invitation_number": invitation["invitation_number"],
        "mutual_match_id": str(invitation["mutual_match_id"]),
        "role": "sender",
        "status": invitation["status"],
        "invitation_version": invitation["invitation_version"],
        "sent_at": invitation["sent_at"],
        "expires_at": invitation["expires_at"],
    }


def member_view(invitation: dict[str, Any], *, user_id: UUID) -> dict[str, Any]:
    """What a member sees.

    A declined invitation shows the sender a single neutral sentence. The
    reason code, the recipient's later activity and any safety context are all
    absent from this shape rather than filtered out of it later.
    """
    is_sender = invitation["sender_user_id"] == user_id
    view: dict[str, Any] = {
        "invitation_id": str(invitation["id"]),
        "invitation_number": invitation["invitation_number"],
        "mutual_match_id": str(invitation["mutual_match_id"]),
        "role": "sender" if is_sender else "recipient",
        "status": invitation["status"],
        "invitation_version": invitation["invitation_version"],
        "sent_at": invitation["sent_at"],
        "expires_at": invitation["expires_at"],
        "message": None,
    }
    if str(invitation["status"]) == InvitationStatus.DECLINED.value and is_sender:
        view["outcome_note"] = "The other member did not continue with this introduction."
    if not is_sender and invitation["message_encrypted"] is not None:
        # The recipient reads the message that was written to them; the sender
        # already knows what they wrote.
        view["message"] = decrypt_private(invitation["message_encrypted"])
    return view


async def list_invitations(session: AsyncSession, user_id: UUID) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT * FROM matchmaking_introduction_invitations "
                "WHERE sender_user_id=:user OR recipient_user_id=:user "
                "ORDER BY created_at DESC LIMIT 200"
            ),
            {"user": user_id},
        )
    ).mappings()
    return [member_view(dict(row), user_id=user_id) for row in rows]


async def get_invitation(
    session: AsyncSession, *, user_id: UUID, invitation_id: UUID
) -> dict[str, Any]:
    rows = (
        await session.execute(
            text(
                "SELECT * FROM matchmaking_introduction_invitations WHERE id=:id "
                "AND (sender_user_id=:user OR recipient_user_id=:user)"
            ),
            {"id": invitation_id, "user": user_id},
        )
    ).mappings()
    found = rows.first()
    if found is None:
        raise VavError("INVITATION_NOT_FOUND", "That introduction was not found.", status_code=404)
    return member_view(dict(found), user_id=user_id)


async def active_invitation_for_match(
    session: AsyncSession, match_id: UUID
) -> dict[str, Any] | None:
    rows = (
        await session.execute(
            text(
                "SELECT * FROM matchmaking_introduction_invitations "
                "WHERE mutual_match_id=:match AND status='accepted' "
                "ORDER BY accepted_at DESC LIMIT 1"
            ),
            {"match": match_id},
        )
    ).mappings()
    found = rows.first()
    return dict(found) if found is not None else None
