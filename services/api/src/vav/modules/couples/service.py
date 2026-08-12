"""Transactional couple-binding and SCOPE assessment service (B16).

The invariants this file exists to hold:

1. A relationship becomes ``active`` in exactly one place — :func:`respond_to_invitation`
   with ``decision='accept'`` sent by the invitee. Every other entry point can
   only create an invitation or end a binding, so a unilateral binding is not
   merely refused, it is unrepresentable (COUPLE-001).
2. Uniqueness of "one active binding per member" is enforced by the
   ``couple_active_members`` table's primary key, not by an application check.
   Two concurrent accepts therefore end with one winner and one 409.
3. The free SCOPE benefit is locked and consumed by *pair key*, so an
   unbind/rebind cycle finds the same consumed row (SCOPE-001).
4. Raw SCOPE answers are encrypted at rest and are only ever decrypted for the
   member who wrote them, or inside the scoring path which returns numbers.
   No endpoint returns another member's raw answers.
5. All business rules live in :mod:`vav.modules.couples.domain`; this layer
   loads state, calls domain, and persists.
"""

# ruff: noqa: E501

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.couples.domain import (
    SCOPE_DIMENSION_ORDER,
    AdviceBlock,
    AssessmentState,
    CoupleRuleError,
    FreeBenefitState,
    InvitationStatus,
    ParticipantState,
    RelationshipState,
    RelationshipStatusPlan,
    ScopeDimension,
    ScopeQuestionSpec,
    ScopeVersionSpec,
    ScopeVersionStatus,
    assemble_report_payload,
    compute_alignment,
    decide_binding,
    decide_free_scope_grant,
    ensure_invitation_actor,
    ensure_raw_answers_readable,
    ensure_report_ready,
    ensure_scope_relationship_active,
    ensure_version_publishable,
    evaluate_report_readiness,
    invitation_expires_at,
    is_invitation_expired,
    pair_key,
    partner_progress_view,
    plan_unbind,
    report_idempotency_key,
    score_scope,
    scores_fingerprint,
    validate_assessment_transition,
    validate_invitation_creation,
    validate_invitation_transition,
    validate_scope_answers,
)
from vav.modules.privacy.crypto import decrypt_private, encrypt_private

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _fail(error: CoupleRuleError, status_code: int = 422) -> VavError:
    """Translate a pure-domain violation into the platform error envelope.

    ``VavError.details`` is a list in this codebase, so the rule's structured
    context is wrapped rather than passed through as a mapping.
    """

    return VavError(
        error.code,
        error.message,
        status_code=status_code,
        details=[error.details] if error.details else None,
    )


def couples_enabled() -> None:
    """DEC-001 safe default: couple features ship switched off."""

    if not get_settings().couples_enabled:
        raise VavError("COUPLES_DISABLED", "Couple features are not enabled.", status_code=503)


def scope_enabled() -> None:
    couples_enabled()
    if not get_settings().couple_scope_enabled:
        raise VavError(
            "COUPLE_SCOPE_DISABLED", "SCOPE assessments are not enabled.", status_code=503
        )


async def _publish(session: AsyncSession, topic: str, aggregate_id: UUID, payload: dict) -> None:
    await session.execute(
        text(
            "INSERT INTO outbox_events (topic,aggregate_type,aggregate_id,payload) "
            "VALUES (:topic,'couple_relationship',:id,CAST(:payload AS jsonb))"
        ),
        {"topic": topic, "id": str(aggregate_id), "payload": _json(payload)},
    )


async def _record_event(
    session: AsyncSession,
    *,
    key: str,
    event_type: str,
    relationship_id: UUID | None,
    invitation_id: UUID | None,
    actor_id: UUID | None,
    actor_kind: str,
    from_state: str | None,
    to_state: str | None,
    reason: str | None = None,
) -> None:
    """Append-only audit line. Every transition in COUPLE-001 writes one."""

    await session.execute(
        text(
            "INSERT INTO couple_binding_events "
            "(pair_key,event_type,relationship_id,invitation_id,actor_id,actor_kind,from_state,to_state,reason) "
            "VALUES (:key,:event_type,:relationship_id,:invitation_id,:actor,:actor_kind,:from_state,:to_state,:reason)"
        ),
        {
            "key": key,
            "event_type": event_type,
            "relationship_id": str(relationship_id) if relationship_id else None,
            "invitation_id": str(invitation_id) if invitation_id else None,
            "actor": str(actor_id) if actor_id else None,
            "actor_kind": actor_kind,
            "from_state": from_state,
            "to_state": to_state,
            "reason": reason,
        },
    )


# ---------------------------------------------------------------------------
# COUPLE-001 relationship status bridge
# ---------------------------------------------------------------------------


async def _apply_status_plan(
    session: AsyncSession, plan: RelationshipStatusPlan, *, actor_id: UUID | None
) -> None:
    """Write one ``member_relationship_statuses`` row inside *our* transaction.

    This mirrors ``vav.modules.matchmaking_entitlements.service.set_relationship_status``
    exactly — same upsert, same history row, same wait-pool exit — but does not
    commit. The B12 helper commits internally, and a binding that committed
    halfway through (one partner's status written, the other's not) would leave
    the pair in an impossible state, so the SQL is replayed here under the
    binding's own transaction instead. If that helper ever grows a
    ``commit=False`` parameter this function should be replaced by a call to it.
    """

    previous = await session.scalar(
        text("SELECT status FROM member_relationship_statuses WHERE user_id=:user_id FOR UPDATE"),
        {"user_id": str(plan.user_id)},
    )
    await session.execute(
        text(
            "INSERT INTO member_relationship_statuses "
            "(user_id,status,source,couple_relationship_id,declared_at,effective_from,updated_by) "
            "VALUES (:user_id,:status,:source,:couple_id,now(),now(),:actor) "
            "ON CONFLICT (user_id) DO UPDATE SET status=EXCLUDED.status,source=EXCLUDED.source,"
            "couple_relationship_id=EXCLUDED.couple_relationship_id,declared_at=EXCLUDED.declared_at,"
            "effective_from=EXCLUDED.effective_from,updated_by=EXCLUDED.updated_by,"
            "version=member_relationship_statuses.version+1,updated_at=now()"
        ),
        {
            "user_id": str(plan.user_id),
            "status": plan.status,
            "source": plan.source,
            "couple_id": (
                str(plan.couple_relationship_id) if plan.couple_relationship_id else None
            ),
            "actor": str(actor_id) if actor_id else None,
        },
    )
    await session.execute(
        text(
            "INSERT INTO member_relationship_status_history "
            "(user_id,from_status,to_status,source,reason,actor_id,actor_kind) "
            "VALUES (:user_id,:from_status,:to_status,:source,:reason,:actor,:actor_kind)"
        ),
        {
            "user_id": str(plan.user_id),
            "from_status": previous,
            "to_status": plan.status,
            "source": plan.source,
            "reason": plan.reason_code,
            "actor": str(actor_id) if actor_id else None,
            "actor_kind": plan.actor_kind,
        },
    )
    # A bound member is not matchmaking-eligible, and neither is a released one
    # (they return to ``undisclosed``), so both directions close the wait pool.
    await session.execute(
        text(
            "UPDATE matchmaking_wait_pool_entries SET status='exited',exited_at=now(),"
            "exit_reason='relationship_status_changed',updated_at=now() "
            "WHERE user_id=:user_id AND status <> 'exited'"
        ),
        {"user_id": str(plan.user_id)},
    )


async def _active_relationship_id(session: AsyncSession, user_id: UUID) -> UUID | None:
    value = await session.scalar(
        text("SELECT relationship_id FROM couple_active_members WHERE user_id=:user_id"),
        {"user_id": str(user_id)},
    )
    return UUID(str(value)) if value else None


# ---------------------------------------------------------------------------
# COUPLE-001 invitations
# ---------------------------------------------------------------------------


async def create_invitation(session: AsyncSession, *, inviter_id: UUID, payload: dict) -> dict:
    """Send an invitation. This does not bind anybody (COUPLE-001)."""

    couples_enabled()
    invitee_id = UUID(str(payload["invitee_user_id"]))
    blocked = bool(
        await session.scalar(
            text(
                "SELECT 1 FROM activity_interaction_restrictions "
                "WHERE status='active' AND ((user_a_id=:a AND user_b_id=:b) OR (user_a_id=:b AND user_b_id=:a)) "
                "LIMIT 1"
            ),
            {"a": str(inviter_id), "b": str(invitee_id)},
        )
    )
    try:
        key = pair_key(inviter_id, invitee_id)
    except CoupleRuleError as error:
        raise _fail(error, status_code=422) from error
    pending = bool(
        await session.scalar(
            text(
                "SELECT 1 FROM couple_invitations WHERE pair_key=:key AND status='pending' LIMIT 1"
            ),
            {"key": key},
        )
    )
    try:
        key, kind = validate_invitation_creation(
            inviter_id=inviter_id,
            invitee_id=invitee_id,
            relationship_kind=str(payload.get("relationship_kind") or "dating"),
            inviter_active_relationship_id=await _active_relationship_id(session, inviter_id),
            invitee_active_relationship_id=await _active_relationship_id(session, invitee_id),
            has_pending_invitation_for_pair=pending,
            blocked=blocked,
        )
    except CoupleRuleError as error:
        raise _fail(error, status_code=409) from error

    now = _now()
    expires_at = invitation_expires_at(
        created_at=now, ttl_hours=get_settings().couple_invitation_ttl_hours
    )
    note = payload.get("note")
    invitation_id = uuid4()
    try:
        await session.execute(
            text(
                "INSERT INTO couple_invitations "
                "(id,pair_key,inviter_user_id,invitee_user_id,relationship_kind,status,note_encrypted,expires_at) "
                "VALUES (:id,:key,:inviter,:invitee,:kind,'pending',:note,:expires_at)"
            ),
            {
                "id": str(invitation_id),
                "key": key,
                "inviter": str(inviter_id),
                "invitee": str(invitee_id),
                "kind": kind.value,
                # Free-text member input is encrypted at rest and never enters
                # an outbox payload, a history row or a log line.
                "note": encrypt_private(note) if note else None,
                "expires_at": expires_at,
            },
        )
    except IntegrityError as exc:
        await session.rollback()
        raise VavError(
            "COUPLE_INVITATION_DUPLICATE",
            "A pending invitation already exists between these two members.",
            status_code=409,
        ) from exc
    await _record_event(
        session,
        key=key,
        event_type="invited",
        relationship_id=None,
        invitation_id=invitation_id,
        actor_id=inviter_id,
        actor_kind="member",
        from_state=None,
        to_state=InvitationStatus.PENDING.value,
    )
    await _publish(
        session,
        "couple.invitation.sent.v1",
        invitation_id,
        {
            "invitation_id": str(invitation_id),
            "inviter_user_id": str(inviter_id),
            "invitee_user_id": str(invitee_id),
            "expires_at": expires_at.isoformat(),
        },
    )
    await session.commit()
    return {
        "invitation_id": str(invitation_id),
        "status": InvitationStatus.PENDING.value,
        "relationship_kind": kind.value,
        "expires_at": expires_at,
    }


async def list_my_invitations(session: AsyncSession, user_id: UUID) -> list[dict]:
    """Invitations this member sent or received.

    The private note is decrypted only for the two parties, which is why the
    row is filtered by ``user_id`` in SQL rather than after the fact.
    """

    couples_enabled()
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,pair_key,inviter_user_id,invitee_user_id,relationship_kind,status,"
                    "note_encrypted,expires_at,responded_at,created_at FROM couple_invitations "
                    "WHERE inviter_user_id=:user_id OR invitee_user_id=:user_id "
                    "ORDER BY created_at DESC LIMIT 50"
                ),
                {"user_id": str(user_id)},
            )
        )
        .mappings()
        .all()
    )
    now = _now()
    items: list[dict] = []
    for row in rows:
        expired = row["status"] == InvitationStatus.PENDING and is_invitation_expired(
            expires_at=row["expires_at"], now=now
        )
        items.append(
            {
                "invitation_id": str(row["id"]),
                "direction": (
                    "outgoing" if UUID(str(row["inviter_user_id"])) == user_id else "incoming"
                ),
                "counterparty_user_id": (
                    str(row["invitee_user_id"])
                    if UUID(str(row["inviter_user_id"])) == user_id
                    else str(row["inviter_user_id"])
                ),
                "relationship_kind": row["relationship_kind"],
                "status": InvitationStatus.EXPIRED.value if expired else row["status"],
                "note": decrypt_private(row["note_encrypted"]) if row["note_encrypted"] else None,
                "expires_at": row["expires_at"],
                "responded_at": row["responded_at"],
                "actionable": expired is False
                and row["status"] == InvitationStatus.PENDING
                and UUID(str(row["invitee_user_id"])) == user_id,
            }
        )
    return items


async def respond_to_invitation(
    session: AsyncSession, *, invitation_id: UUID, user_id: UUID, payload: dict
) -> dict:
    """Accept or reject. The *only* path that can create an active binding.

    The invitation row is locked first, so two taps on "accept" resolve to one
    binding, and the unique key on ``couple_active_members`` catches the case
    where the same member races an acceptance in two different invitations.
    """

    couples_enabled()
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,pair_key,inviter_user_id,invitee_user_id,relationship_kind,status,expires_at "
                    "FROM couple_invitations WHERE id=:id FOR UPDATE"
                ),
                {"id": str(invitation_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("COUPLE_INVITATION_NOT_FOUND", "Invitation not found.", status_code=404)
    inviter_id = UUID(str(row["inviter_user_id"]))
    invitee_id = UUID(str(row["invitee_user_id"]))
    if user_id not in (inviter_id, invitee_id):
        # Not 403-with-detail: a stranger learns nothing about the invitation.
        raise VavError("COUPLE_INVITATION_NOT_FOUND", "Invitation not found.", status_code=404)

    decision = str(payload["decision"])
    target = (
        InvitationStatus.ACCEPTED.value if decision == "accept" else InvitationStatus.REJECTED.value
    )
    if decision == "reject":
        try:
            validate_invitation_transition(row["status"], target)
            ensure_invitation_actor(
                target=target, actor_id=user_id, inviter_id=inviter_id, invitee_id=invitee_id
            )
        except CoupleRuleError as error:
            raise _fail(error, status_code=409) from error
        await session.execute(
            text(
                "UPDATE couple_invitations SET status='rejected',responded_at=now(),"
                "decline_reason_code=:reason,updated_at=now() WHERE id=:id"
            ),
            {"reason": payload.get("reason_code"), "id": str(invitation_id)},
        )
        await _record_event(
            session,
            key=row["pair_key"],
            event_type="rejected",
            relationship_id=None,
            invitation_id=invitation_id,
            actor_id=user_id,
            actor_kind="member",
            from_state=row["status"],
            to_state=target,
        )
        await session.commit()
        return {"invitation_id": str(invitation_id), "status": target}

    relationship_id = uuid4()
    try:
        plan = decide_binding(
            inviter_id=inviter_id,
            invitee_id=invitee_id,
            acceptor_id=user_id,
            invitation_status=row["status"],
            relationship_kind=row["relationship_kind"],
            relationship_id=relationship_id,
            acceptor_active_relationship_id=await _active_relationship_id(session, user_id),
            inviter_active_relationship_id=await _active_relationship_id(session, inviter_id),
            expires_at=row["expires_at"],
            now=_now(),
        )
    except CoupleRuleError as error:
        raise _fail(error, status_code=409) from error

    await session.execute(
        text(
            "INSERT INTO couple_relationships "
            "(id,pair_key,user_low_id,user_high_id,relationship_kind,state,invitation_id,bound_at) "
            "VALUES (:id,:key,:low,:high,:kind,'active',:invitation_id,now())"
        ),
        {
            "id": str(relationship_id),
            "key": plan.pair_key,
            "low": str(plan.members[0]),
            "high": str(plan.members[1]),
            "kind": plan.relationship_kind.value,
            "invitation_id": str(invitation_id),
        },
    )
    try:
        for member in plan.members:
            await session.execute(
                text(
                    "INSERT INTO couple_active_members (user_id,relationship_id,pair_key) "
                    "VALUES (:user_id,:relationship_id,:key)"
                ),
                {
                    "user_id": str(member),
                    "relationship_id": str(relationship_id),
                    "key": plan.pair_key,
                },
            )
    except IntegrityError as exc:
        # The primary key on couple_active_members is the real guard against a
        # member ending up in two active bindings; the domain check above is the
        # fast path, this is the race-proof one.
        await session.rollback()
        raise VavError(
            "COUPLE_RELATIONSHIP_CONFLICT",
            "One of the two members is already in an active binding.",
            status_code=409,
        ) from exc

    await session.execute(
        text(
            "UPDATE couple_invitations SET status='accepted',responded_at=now(),updated_at=now() "
            "WHERE id=:id"
        ),
        {"id": str(invitation_id)},
    )
    for status_plan in plan.status_plans:
        await _apply_status_plan(session, status_plan, actor_id=user_id)
    await _record_event(
        session,
        key=plan.pair_key,
        event_type="bound",
        relationship_id=relationship_id,
        invitation_id=invitation_id,
        actor_id=user_id,
        actor_kind="member",
        from_state=InvitationStatus.PENDING.value,
        to_state=RelationshipState.ACTIVE.value,
    )
    await _publish(
        session,
        "couple.relationship.bound.v1",
        relationship_id,
        {
            "relationship_id": str(relationship_id),
            "pair_key": plan.pair_key,
            "members": [str(member) for member in plan.members],
            "relationship_kind": plan.relationship_kind.value,
        },
    )
    await session.commit()
    return {
        "invitation_id": str(invitation_id),
        "status": InvitationStatus.ACCEPTED.value,
        "relationship_id": str(relationship_id),
        "relationship_kind": plan.relationship_kind.value,
        "state": RelationshipState.ACTIVE.value,
    }


async def cancel_invitation(
    session: AsyncSession, *, invitation_id: UUID, user_id: UUID
) -> dict:
    couples_enabled()
    row = (
        (
            await session.execute(
                text(
                    "SELECT pair_key,inviter_user_id,invitee_user_id,status FROM couple_invitations "
                    "WHERE id=:id FOR UPDATE"
                ),
                {"id": str(invitation_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("COUPLE_INVITATION_NOT_FOUND", "Invitation not found.", status_code=404)
    try:
        validate_invitation_transition(row["status"], InvitationStatus.CANCELLED)
        ensure_invitation_actor(
            target=InvitationStatus.CANCELLED.value,
            actor_id=user_id,
            inviter_id=UUID(str(row["inviter_user_id"])),
            invitee_id=UUID(str(row["invitee_user_id"])),
        )
    except CoupleRuleError as error:
        raise _fail(error, status_code=409) from error
    await session.execute(
        text(
            "UPDATE couple_invitations SET status='cancelled',responded_at=now(),updated_at=now() "
            "WHERE id=:id"
        ),
        {"id": str(invitation_id)},
    )
    await _record_event(
        session,
        key=row["pair_key"],
        event_type="cancelled",
        relationship_id=None,
        invitation_id=invitation_id,
        actor_id=user_id,
        actor_kind="member",
        from_state=row["status"],
        to_state=InvitationStatus.CANCELLED.value,
    )
    await session.commit()
    return {"invitation_id": str(invitation_id), "status": InvitationStatus.CANCELLED.value}


async def expire_invitations(session: AsyncSession) -> dict:
    """Background sweep. Expiry is also evaluated on read, so this is hygiene."""

    couples_enabled()
    result = await session.execute(
        text(
            "UPDATE couple_invitations SET status='expired',updated_at=now() "
            "WHERE status='pending' AND expires_at <= now()"
        )
    )
    await session.commit()
    return {"expired": int(result.rowcount or 0)}


# ---------------------------------------------------------------------------
# COUPLE-001 relationship read and unbind
# ---------------------------------------------------------------------------


async def get_my_relationship(session: AsyncSession, user_id: UUID) -> dict:
    couples_enabled()
    row = (
        (
            await session.execute(
                text(
                    "SELECT r.id,r.pair_key,r.user_low_id,r.user_high_id,r.relationship_kind,r.state,r.bound_at "
                    "FROM couple_relationships r JOIN couple_active_members m ON m.relationship_id=r.id "
                    "WHERE m.user_id=:user_id"
                ),
                {"user_id": str(user_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return {"state": "unbound", "relationship_id": None, "partner_user_id": None}
    low = UUID(str(row["user_low_id"]))
    high = UUID(str(row["user_high_id"]))
    return {
        "relationship_id": str(row["id"]),
        "state": row["state"],
        "relationship_kind": row["relationship_kind"],
        "partner_user_id": str(high if low == user_id else low),
        "bound_at": row["bound_at"],
    }


async def _unbind(
    session: AsyncSession,
    *,
    relationship_id: UUID,
    actor_id: UUID | None,
    actor_kind: str,
    reason: str | None,
) -> dict:
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,pair_key,user_low_id,user_high_id,state FROM couple_relationships "
                    "WHERE id=:id FOR UPDATE"
                ),
                {"id": str(relationship_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError(
            "COUPLE_RELATIONSHIP_NOT_FOUND", "Relationship not found.", status_code=404
        )
    members = [UUID(str(row["user_low_id"])), UUID(str(row["user_high_id"]))]
    try:
        plan = plan_unbind(
            relationship_state=row["state"],
            members=members,
            actor_id=actor_id,
            actor_kind=actor_kind,
            reason=reason,
            key=row["pair_key"],
        )
    except CoupleRuleError as error:
        raise _fail(error, status_code=409) from error

    await session.execute(
        text(
            "UPDATE couple_relationships SET state='unbound',unbound_at=now(),unbound_by=:actor,"
            "unbind_reason=:reason,updated_at=now() WHERE id=:id AND state='active'"
        ),
        {
            "actor": str(actor_id) if actor_id else None,
            "reason": plan.reason or None,
            "id": str(relationship_id),
        },
    )
    # Releasing the seats is what allows either member to bind again later. The
    # relationship row itself is kept forever: the free-benefit ledger is keyed
    # on the pair, so history must remain explainable.
    await session.execute(
        text("DELETE FROM couple_active_members WHERE relationship_id=:id"),
        {"id": str(relationship_id)},
    )
    # An assessment in flight for a relationship that just ended is cancelled
    # rather than left collecting intimate answers. The consumed free benefit is
    # deliberately *not* returned (SCOPE-001).
    await session.execute(
        text(
            "UPDATE scope_assessments SET state='cancelled',cancelled_at=now(),"
            "cancel_reason='relationship_unbound',updated_at=now() "
            "WHERE relationship_id=:id AND state IN ('collecting','completed')"
        ),
        {"id": str(relationship_id)},
    )
    for status_plan in plan.status_plans:
        await _apply_status_plan(session, status_plan, actor_id=actor_id)
    await _record_event(
        session,
        key=plan.pair_key,
        event_type=plan.event_type,
        relationship_id=relationship_id,
        invitation_id=None,
        actor_id=actor_id,
        actor_kind=actor_kind,
        from_state=RelationshipState.ACTIVE.value,
        to_state=RelationshipState.UNBOUND.value,
        reason=plan.reason or None,
    )
    await _publish(
        session,
        "couple.relationship.unbound.v1",
        relationship_id,
        {
            "relationship_id": str(relationship_id),
            "pair_key": plan.pair_key,
            "members": [str(member) for member in plan.members],
            "actor_kind": actor_kind,
        },
    )
    await session.commit()
    return {
        "relationship_id": str(relationship_id),
        "state": RelationshipState.UNBOUND.value,
        "members": [str(member) for member in plan.members],
    }


async def unbind_my_relationship(
    session: AsyncSession, *, user_id: UUID, reason: str | None
) -> dict:
    """Either partner may end a binding alone.

    Deliberately asymmetric with binding: requiring both signatures to leave
    would let one partner hold the other in a declared relationship.
    """

    couples_enabled()
    relationship_id = await _active_relationship_id(session, user_id)
    if relationship_id is None:
        raise VavError(
            "COUPLE_RELATIONSHIP_NOT_FOUND", "You are not in an active binding.", status_code=404
        )
    return await _unbind(
        session,
        relationship_id=relationship_id,
        actor_id=user_id,
        actor_kind="member",
        reason=reason,
    )


async def admin_unbind_relationship(
    session: AsyncSession, *, relationship_id: UUID, actor_id: UUID, reason: str
) -> dict:
    couples_enabled()
    return await _unbind(
        session,
        relationship_id=relationship_id,
        actor_id=actor_id,
        actor_kind="admin",
        reason=reason,
    )


async def list_binding_events(session: AsyncSession, *, relationship_id: UUID) -> list[dict]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT event_type,actor_id,actor_kind,from_state,to_state,reason,created_at "
                    "FROM couple_binding_events WHERE relationship_id=:id ORDER BY created_at"
                ),
                {"id": str(relationship_id)},
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# SCOPE-001 versioned question bank (administrator-authored)
# ---------------------------------------------------------------------------


async def create_scope_version(session: AsyncSession, *, actor_id: UUID, payload: dict) -> dict:
    scope_enabled()
    version_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO scope_assessment_versions "
            "(id,version_code,semantic_version,algorithm_version,status,created_by) "
            "VALUES (:id,:code,:semver,:algorithm,'draft',:actor)"
        ),
        {
            "id": str(version_id),
            "code": payload["version_code"],
            "semver": payload["semantic_version"],
            "algorithm": payload["algorithm_version"],
            "actor": str(actor_id),
        },
    )
    await session.commit()
    return {"version_id": str(version_id), "status": ScopeVersionStatus.DRAFT.value}


async def add_scope_question(
    session: AsyncSession, *, version_id: UUID, actor_id: UUID, payload: dict
) -> dict:
    """Author one question. The shipped bank is empty by design (DEC-001)."""

    scope_enabled()
    status = await session.scalar(
        text("SELECT status FROM scope_assessment_versions WHERE id=:id FOR UPDATE"),
        {"id": str(version_id)},
    )
    if status is None:
        raise VavError("SCOPE_VERSION_NOT_FOUND", "SCOPE version not found.", status_code=404)
    if status != ScopeVersionStatus.DRAFT:
        # Published versions are immutable: editing one would silently change
        # the meaning of every report already generated from it.
        raise VavError(
            "SCOPE_VERSION_NOT_DRAFT",
            "Questions can only be added while a version is a draft.",
            status_code=409,
        )
    try:
        spec = ScopeQuestionSpec(
            question_id=uuid4(),
            question_code=payload["question_code"],
            dimension=ScopeDimension(payload["dimension"]),
            weight=int(payload.get("weight", 1)),
            scale_min=int(payload.get("scale_min", 1)),
            scale_max=int(payload.get("scale_max", 5)),
            reverse_scored=bool(payload.get("reverse_scored", False)),
            position=int(payload.get("position", 0)),
        )
    except (CoupleRuleError, ValueError) as error:
        if isinstance(error, CoupleRuleError):
            raise _fail(error) from error
        raise VavError("SCOPE_DIMENSION_UNKNOWN", str(error), status_code=422) from error
    try:
        await session.execute(
            text(
                "INSERT INTO scope_assessment_questions "
                "(id,version_id,question_code,dimension,prompt_text,weight,scale_min,scale_max,reverse_scored,position) "
                "VALUES (:id,:version_id,:code,:dimension,:prompt,:weight,:scale_min,:scale_max,:reverse,:position)"
            ),
            {
                "id": str(spec.question_id),
                "version_id": str(version_id),
                "code": spec.question_code,
                "dimension": spec.dimension.value,
                "prompt": payload["prompt_text"],
                "weight": spec.weight,
                "scale_min": spec.scale_min,
                "scale_max": spec.scale_max,
                "reverse": spec.reverse_scored,
                "position": spec.position,
            },
        )
    except IntegrityError as exc:
        await session.rollback()
        raise VavError(
            "SCOPE_QUESTION_CODE_DUPLICATE",
            "That question code already exists in this version.",
            status_code=409,
        ) from exc
    await session.commit()
    return {"question_id": str(spec.question_id), "version_id": str(version_id)}


async def _load_version_spec(session: AsyncSession, version_id: UUID) -> ScopeVersionSpec:
    header = (
        (
            await session.execute(
                text(
                    "SELECT version_code,semantic_version,algorithm_version,status "
                    "FROM scope_assessment_versions WHERE id=:id"
                ),
                {"id": str(version_id)},
            )
        )
        .mappings()
        .first()
    )
    if header is None:
        raise VavError("SCOPE_VERSION_NOT_FOUND", "SCOPE version not found.", status_code=404)
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,question_code,dimension,weight,scale_min,scale_max,reverse_scored,position "
                    "FROM scope_assessment_questions WHERE version_id=:id ORDER BY position,question_code"
                ),
                {"id": str(version_id)},
            )
        )
        .mappings()
        .all()
    )
    return ScopeVersionSpec(
        version_code=header["version_code"],
        semantic_version=header["semantic_version"],
        algorithm_version=header["algorithm_version"],
        questions=tuple(
            ScopeQuestionSpec(
                question_id=UUID(str(row["id"])),
                question_code=row["question_code"],
                dimension=ScopeDimension(row["dimension"]),
                weight=int(row["weight"]),
                scale_min=int(row["scale_min"]),
                scale_max=int(row["scale_max"]),
                reverse_scored=bool(row["reverse_scored"]),
                position=int(row["position"]),
            )
            for row in rows
        ),
    )


async def publish_scope_version(
    session: AsyncSession, *, version_id: UUID, actor_id: UUID
) -> dict:
    """Publish only once all five dimensions are actually authored."""

    scope_enabled()
    spec = await _load_version_spec(session, version_id)
    try:
        ensure_version_publishable(spec)
    except CoupleRuleError as error:
        raise _fail(error, status_code=409) from error
    result = await session.execute(
        text(
            "UPDATE scope_assessment_versions SET status='published',published_by=:actor,"
            "published_at=now(),updated_at=now() WHERE id=:id AND status='draft'"
        ),
        {"actor": str(actor_id), "id": str(version_id)},
    )
    if result.rowcount == 0:
        raise VavError(
            "SCOPE_VERSION_NOT_DRAFT", "Only a draft version can be published.", status_code=409
        )
    await session.commit()
    return {"version_id": str(version_id), "status": ScopeVersionStatus.PUBLISHED.value}


async def list_scope_versions(session: AsyncSession) -> list[dict]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,version_code,semantic_version,algorithm_version,status,published_at "
                    "FROM scope_assessment_versions ORDER BY created_at DESC"
                )
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# SCOPE-001 the free-per-pair assessment
# ---------------------------------------------------------------------------


async def _load_free_benefit(session: AsyncSession, key: str, members: tuple[UUID, UUID]) -> FreeBenefitState:
    """Load (or create) the pair's free-benefit ledger under a row lock.

    The row is created on first use with ``granted=1`` and never deleted, which
    is exactly what makes an unbind/rebind cycle unable to mint a second free
    assessment (SCOPE-001).
    """

    await session.execute(
        text(
            "INSERT INTO couple_scope_free_benefits (pair_key,user_low_id,user_high_id,granted,consumed) "
            "VALUES (:key,:low,:high,:granted,0) ON CONFLICT (pair_key) DO NOTHING"
        ),
        {
            "key": key,
            "low": str(members[0]),
            "high": str(members[1]),
            "granted": get_settings().couple_scope_free_assessments_per_pair,
        },
    )
    row = (
        (
            await session.execute(
                text(
                    "SELECT granted,consumed FROM couple_scope_free_benefits "
                    "WHERE pair_key=:key FOR UPDATE"
                ),
                {"key": key},
            )
        )
        .mappings()
        .first()
    )
    return FreeBenefitState(
        pair_key=key, granted=int(row["granted"]), consumed=int(row["consumed"])
    )


async def start_scope_assessment(session: AsyncSession, *, user_id: UUID, payload: dict) -> dict:
    scope_enabled()
    relationship = (
        (
            await session.execute(
                text(
                    "SELECT r.id,r.pair_key,r.user_low_id,r.user_high_id,r.state FROM couple_relationships r "
                    "JOIN couple_active_members m ON m.relationship_id=r.id WHERE m.user_id=:user_id "
                    "FOR UPDATE OF r"
                ),
                {"user_id": str(user_id)},
            )
        )
        .mappings()
        .first()
    )
    if relationship is None:
        raise VavError(
            "COUPLE_RELATIONSHIP_NOT_FOUND", "You are not in an active binding.", status_code=404
        )
    try:
        ensure_scope_relationship_active(relationship["state"])
    except CoupleRuleError as error:
        raise _fail(error, status_code=409) from error

    version_id = UUID(str(payload["version_id"]))
    version_status = await session.scalar(
        text("SELECT status FROM scope_assessment_versions WHERE id=:id"), {"id": str(version_id)}
    )
    if version_status is None:
        raise VavError("SCOPE_VERSION_NOT_FOUND", "SCOPE version not found.", status_code=404)
    if version_status != ScopeVersionStatus.PUBLISHED:
        raise VavError(
            "SCOPE_VERSION_NOT_PUBLISHED",
            "Only a published SCOPE version can be started.",
            status_code=409,
        )

    relationship_id = UUID(str(relationship["id"]))
    key = relationship["pair_key"]
    members = (UUID(str(relationship["user_low_id"])), UUID(str(relationship["user_high_id"])))

    existing = (
        (
            await session.execute(
                text(
                    "SELECT id,state FROM scope_assessments WHERE relationship_id=:id "
                    "AND state IN ('collecting','completed','report_ready')"
                ),
                {"id": str(relationship_id)},
            )
        )
        .mappings()
        .first()
    )
    if existing is not None:
        return {
            "assessment_id": str(existing["id"]),
            "state": existing["state"],
            "created": False,
        }

    benefit = await _load_free_benefit(session, key, members)
    try:
        decision = decide_free_scope_grant(benefit)
    except CoupleRuleError as error:
        # 402-style semantics: the pair must buy an assessment (B17) instead.
        raise _fail(error, status_code=409) from error
    await session.execute(
        text(
            "UPDATE couple_scope_free_benefits SET consumed=consumed+1,consumed_at=now(),"
            "consumed_relationship_id=:relationship_id,updated_at=now() WHERE pair_key=:key"
        ),
        {"relationship_id": str(relationship_id), "key": key},
    )

    assessment_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO scope_assessments "
            "(id,relationship_id,pair_key,version_id,state,entitlement_source,free_benefit_key) "
            "VALUES (:id,:relationship_id,:key,:version_id,'collecting','free',:benefit_key)"
        ),
        {
            "id": str(assessment_id),
            "relationship_id": str(relationship_id),
            "key": key,
            "version_id": str(version_id),
            "benefit_key": decision.idempotency_key,
        },
    )
    for member in members:
        await session.execute(
            text(
                "INSERT INTO scope_participant_submissions (id,assessment_id,user_id,status) "
                "VALUES (:id,:assessment_id,:user_id,'not_started')"
            ),
            {
                "id": str(uuid4()),
                "assessment_id": str(assessment_id),
                "user_id": str(member),
            },
        )
    await _publish(
        session,
        "couple.scope.started.v1",
        assessment_id,
        {
            "assessment_id": str(assessment_id),
            "relationship_id": str(relationship_id),
            "pair_key": key,
            "version_id": str(version_id),
        },
    )
    await session.commit()
    return {
        "assessment_id": str(assessment_id),
        "state": AssessmentState.COLLECTING.value,
        "created": True,
        "free_benefit_remaining": decision.remaining_after,
    }


async def _assessment_for_member(
    session: AsyncSession, assessment_id: UUID, user_id: UUID, *, lock: bool = False
) -> dict:
    suffix = " FOR UPDATE OF a" if lock else ""
    row = (
        (
            await session.execute(
                text(
                    "SELECT a.id,a.relationship_id,a.pair_key,a.version_id,a.state,r.user_low_id,r.user_high_id,r.state AS relationship_state "
                    "FROM scope_assessments a JOIN couple_relationships r ON r.id=a.relationship_id "
                    "WHERE a.id=:id AND (r.user_low_id=:user_id OR r.user_high_id=:user_id)" + suffix
                ),
                {"id": str(assessment_id), "user_id": str(user_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("SCOPE_ASSESSMENT_NOT_FOUND", "Assessment not found.", status_code=404)
    return dict(row)


async def get_scope_assessment(
    session: AsyncSession, *, assessment_id: UUID, user_id: UUID
) -> dict:
    """The member's own view.

    Returns the caller's own draft answers and *only the progress* of their
    partner. There is no code path here, or anywhere else, that decrypts the
    partner's answer blob (SCOPE-001).
    """

    scope_enabled()
    assessment = await _assessment_for_member(session, assessment_id, user_id)
    rows = (
        (
            await session.execute(
                text(
                    "SELECT user_id,status,submitted_at,answers_encrypted FROM scope_participant_submissions "
                    "WHERE assessment_id=:id"
                ),
                {"id": str(assessment_id)},
            )
        )
        .mappings()
        .all()
    )
    mine: dict[str, int] = {}
    my_status = ParticipantState.NOT_STARTED.value
    partners: list[dict] = []
    for row in rows:
        owner_id = UUID(str(row["user_id"]))
        if owner_id == user_id:
            my_status = row["status"]
            if row["answers_encrypted"]:
                mine = json.loads(decrypt_private(row["answers_encrypted"]))
        else:
            partners.append(
                partner_progress_view(
                    user_id=owner_id, status=row["status"], submitted_at=row["submitted_at"]
                )
            )
    return {
        "assessment_id": str(assessment_id),
        "state": assessment["state"],
        "version_id": str(assessment["version_id"]),
        "my_status": my_status,
        "my_answers": mine,
        "partner": partners[0] if partners else None,
    }


async def read_my_raw_answers(
    session: AsyncSession, *, assessment_id: UUID, user_id: UUID, owner_id: UUID
) -> dict:
    """Explicit raw-answer read, guarded by the domain seal.

    Exists as its own endpoint so the seal has a single, obvious choke point
    that a reviewer can find. ``owner_id`` is taken from the request path, so
    asking for anybody else's answers fails loudly instead of silently
    returning the caller's own.
    """

    scope_enabled()
    await _assessment_for_member(session, assessment_id, user_id)
    try:
        ensure_raw_answers_readable(viewer_id=user_id, owner_id=owner_id)
    except CoupleRuleError as error:
        raise _fail(error, status_code=403) from error
    blob = await session.scalar(
        text(
            "SELECT answers_encrypted FROM scope_participant_submissions "
            "WHERE assessment_id=:id AND user_id=:user_id"
        ),
        {"id": str(assessment_id), "user_id": str(owner_id)},
    )
    return {"answers": json.loads(decrypt_private(blob)) if blob else {}}


async def save_scope_answers(
    session: AsyncSession, *, assessment_id: UUID, user_id: UUID, payload: dict
) -> dict:
    """Autosave a draft or seal a submission.

    A sealed submission is final: reopening it would let a member watch the
    report move as they edited, which is a side channel into the partner's
    answers. Only an administrator can reset a submission, and that is audited.
    """

    scope_enabled()
    assessment = await _assessment_for_member(session, assessment_id, user_id, lock=True)
    try:
        ensure_scope_relationship_active(assessment["relationship_state"])
    except CoupleRuleError as error:
        raise _fail(error, status_code=409) from error
    if assessment["state"] != AssessmentState.COLLECTING:
        raise VavError(
            "SCOPE_ASSESSMENT_CLOSED",
            "This assessment is no longer collecting answers.",
            status_code=409,
        )
    current = (
        (
            await session.execute(
                text(
                    "SELECT status FROM scope_participant_submissions "
                    "WHERE assessment_id=:id AND user_id=:user_id FOR UPDATE"
                ),
                {"id": str(assessment_id), "user_id": str(user_id)},
            )
        )
        .mappings()
        .first()
    )
    if current is None:
        raise VavError(
            "SCOPE_PARTICIPANT_NOT_FOUND", "You are not a participant.", status_code=404
        )
    if current["status"] == ParticipantState.SUBMITTED:
        raise VavError(
            "SCOPE_SUBMISSION_SEALED",
            "Your SCOPE answers have already been submitted and cannot be changed.",
            status_code=409,
        )

    submit = bool(payload.get("submit", False))
    version = await _load_version_spec(session, UUID(str(assessment["version_id"])))
    try:
        cleaned = validate_scope_answers(
            version, dict(payload.get("answers") or {}), partial=not submit
        )
    except CoupleRuleError as error:
        raise _fail(error) from error

    await session.execute(
        text(
            "UPDATE scope_participant_submissions SET answers_encrypted=:answers,"
            "answer_count=:count,status=:status,submitted_at=CASE WHEN :submit THEN now() ELSE submitted_at END,"
            "updated_at=now() WHERE assessment_id=:id AND user_id=:user_id"
        ),
        {
            # Sealed at rest as well as in the API: the blob is opaque to
            # anybody reading the table directly.
            "answers": encrypt_private(_json(cleaned)),
            "count": len(cleaned),
            "status": (
                ParticipantState.SUBMITTED.value if submit else ParticipantState.IN_PROGRESS.value
            ),
            "submit": submit,
            "id": str(assessment_id),
            "user_id": str(user_id),
        },
    )
    result: dict[str, Any] = {
        "assessment_id": str(assessment_id),
        "status": (
            ParticipantState.SUBMITTED.value if submit else ParticipantState.IN_PROGRESS.value
        ),
        "answer_count": len(cleaned),
    }
    if submit:
        result.update(await _try_complete(session, assessment_id=assessment_id))
    await session.commit()
    return result


async def _try_complete(session: AsyncSession, *, assessment_id: UUID) -> dict:
    """Evaluate the completion barrier and, if open, score and report.

    Called after every submission. Until both partners are in, this returns
    ``report_ready=False`` and writes nothing — no partial score, no preview.
    """

    rows = (
        (
            await session.execute(
                text(
                    "SELECT user_id,status,answers_encrypted FROM scope_participant_submissions "
                    "WHERE assessment_id=:id FOR UPDATE"
                ),
                {"id": str(assessment_id)},
            )
        )
        .mappings()
        .all()
    )
    states = {UUID(str(row["user_id"])): row["status"] for row in rows}
    readiness = evaluate_report_readiness(
        expected_members=list(states), states=states
    )
    if not readiness.ready:
        return {
            "report_ready": False,
            "waiting_on": [str(user) for user in readiness.waiting_on],
            "reason_code": readiness.reason_code,
        }
    ensure_report_ready(readiness)

    header = (
        (
            await session.execute(
                text("SELECT version_id,state FROM scope_assessments WHERE id=:id"),
                {"id": str(assessment_id)},
            )
        )
        .mappings()
        .first()
    )
    try:
        validate_assessment_transition(header["state"], AssessmentState.COMPLETED)
    except CoupleRuleError as error:
        raise _fail(error, status_code=409) from error
    version = await _load_version_spec(session, UUID(str(header["version_id"])))

    scores = {}
    for row in rows:
        owner_id = UUID(str(row["user_id"]))
        answers = json.loads(decrypt_private(row["answers_encrypted"]))
        score_set = score_scope(version, answers)
        scores[owner_id] = score_set
        for dimension_score in score_set.dimensions:
            await session.execute(
                text(
                    "INSERT INTO scope_dimension_scores "
                    "(id,assessment_id,user_id,dimension,raw_total,min_total,max_total,normalized_score,algorithm_version) "
                    "VALUES (:id,:assessment_id,:user_id,:dimension,:raw,:min_total,:max_total,:normalized,:algorithm) "
                    "ON CONFLICT (assessment_id,user_id,dimension) DO UPDATE SET "
                    "raw_total=EXCLUDED.raw_total,min_total=EXCLUDED.min_total,max_total=EXCLUDED.max_total,"
                    "normalized_score=EXCLUDED.normalized_score,algorithm_version=EXCLUDED.algorithm_version"
                ),
                {
                    "id": str(uuid4()),
                    "assessment_id": str(assessment_id),
                    "user_id": str(owner_id),
                    "dimension": dimension_score.dimension.value,
                    "raw": dimension_score.raw_total,
                    "min_total": dimension_score.min_total,
                    "max_total": dimension_score.max_total,
                    "normalized": str(dimension_score.normalized),
                    "algorithm": score_set.algorithm_version,
                },
            )
    ordered = sorted(scores, key=str)
    alignment = compute_alignment(scores[ordered[0]], scores[ordered[1]])
    now = _now()
    payload = assemble_report_payload(
        scores=scores, alignment=alignment, advice=None, generated_at=now
    )
    report_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO scope_reports "
            "(id,assessment_id,version_id,algorithm_version,scores,scores_fingerprint,idempotency_key,advice_status,generated_at) "
            "VALUES (:id,:assessment_id,:version_id,:algorithm,CAST(:scores AS jsonb),:fingerprint,:key,'absent',now()) "
            "ON CONFLICT (idempotency_key) DO NOTHING"
        ),
        {
            "id": str(report_id),
            "assessment_id": str(assessment_id),
            "version_id": str(header["version_id"]),
            "algorithm": version.algorithm_version,
            "scores": _json(payload["scores"]),
            "fingerprint": scores_fingerprint(scores[ordered[0]]),
            "key": report_idempotency_key(assessment_id, version.algorithm_version),
        },
    )
    await session.execute(
        text(
            "UPDATE scope_assessments SET state='report_ready',completed_at=now(),updated_at=now() "
            "WHERE id=:id"
        ),
        {"id": str(assessment_id)},
    )
    await _publish(
        session,
        "couple.scope.report.ready.v1",
        assessment_id,
        {"assessment_id": str(assessment_id), "algorithm_version": version.algorithm_version},
    )
    return {"report_ready": True, "reason_code": readiness.reason_code}


async def get_scope_report(session: AsyncSession, *, assessment_id: UUID, user_id: UUID) -> dict:
    """Return the report to a participant.

    ``scores`` is the deterministic block re-derivable from the sealed answers;
    ``advice`` is the AI narrative, decrypted separately and clearly labelled.
    Neither contains any partner's raw answers.
    """

    scope_enabled()
    await _assessment_for_member(session, assessment_id, user_id)
    row = (
        (
            await session.execute(
                text(
                    "SELECT scores,scores_fingerprint,algorithm_version,advice_status,advice_encrypted,"
                    "advice_model,advice_prompt_version,advice_generated_at,advice_disclaimer_code,generated_at "
                    "FROM scope_reports WHERE assessment_id=:id"
                ),
                {"id": str(assessment_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError(
            "SCOPE_REPORT_BARRIER",
            "The SCOPE report is generated only after both partners have submitted.",
            status_code=409,
        )
    advice = None
    if row["advice_encrypted"]:
        advice = {
            "is_ai_generated": True,
            "model_code": row["advice_model"],
            "prompt_version": row["advice_prompt_version"],
            "generated_at": row["advice_generated_at"],
            "disclaimer_code": row["advice_disclaimer_code"],
            "body": decrypt_private(row["advice_encrypted"]),
        }
    return {
        "assessment_id": str(assessment_id),
        "algorithm_version": row["algorithm_version"],
        "scores": row["scores"],
        "scores_fingerprint": row["scores_fingerprint"],
        "advice": advice,
        "advice_status": row["advice_status"],
        "generated_at": row["generated_at"],
        "dimensions": [dimension.value for dimension in SCOPE_DIMENSION_ORDER],
    }


async def attach_scope_advice(
    session: AsyncSession, *, assessment_id: UUID, actor_id: UUID, payload: dict
) -> dict:
    """Store the AI narrative in its own columns, never inside ``scores``."""

    scope_enabled()
    if not get_settings().couple_scope_ai_advice_enabled:
        raise VavError(
            "COUPLE_SCOPE_ADVICE_DISABLED",
            "AI advice generation is not enabled.",
            status_code=503,
        )
    exists = await session.scalar(
        text("SELECT 1 FROM scope_reports WHERE assessment_id=:id FOR UPDATE"),
        {"id": str(assessment_id)},
    )
    if not exists:
        raise VavError(
            "SCOPE_REPORT_NOT_FOUND", "No report exists for this assessment.", status_code=404
        )
    now = _now()
    try:
        advice = AdviceBlock(
            body=payload["body"],
            model_code=payload["model_code"],
            prompt_version=payload["prompt_version"],
            generated_at=now,
            disclaimer_code=str(payload.get("disclaimer_code") or "scope_ai_advice"),
        )
    except CoupleRuleError as error:
        raise _fail(error) from error
    await session.execute(
        text(
            "UPDATE scope_reports SET advice_encrypted=:body,advice_model=:model,"
            "advice_prompt_version=:prompt_version,advice_generated_at=now(),"
            "advice_disclaimer_code=:disclaimer,advice_status='generated',updated_at=now() "
            "WHERE assessment_id=:id"
        ),
        {
            "body": encrypt_private(advice.body),
            "model": advice.model_code,
            "prompt_version": advice.prompt_version,
            "disclaimer": advice.disclaimer_code,
            "id": str(assessment_id),
        },
    )
    await session.commit()
    return {"assessment_id": str(assessment_id), "advice_status": "generated"}


async def admin_list_relationships(session: AsyncSession, *, state: str | None) -> list[dict]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,pair_key,user_low_id,user_high_id,relationship_kind,state,bound_at,unbound_at "
                    "FROM couple_relationships WHERE (:state IS NULL OR state=:state) "
                    "ORDER BY created_at DESC LIMIT 200"
                ),
                {"state": state},
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


async def admin_free_benefit(session: AsyncSession, *, key: str) -> dict:
    """Support view: why did this pair not get a free assessment?"""

    row = (
        (
            await session.execute(
                text(
                    "SELECT pair_key,granted,consumed,consumed_at,consumed_relationship_id "
                    "FROM couple_scope_free_benefits WHERE pair_key=:key"
                ),
                {"key": key},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return {"pair_key": key, "granted": 0, "consumed": 0, "remaining": 0}
    state = FreeBenefitState(
        pair_key=key, granted=int(row["granted"]), consumed=int(row["consumed"])
    )
    return {**dict(row), "remaining": state.remaining}
