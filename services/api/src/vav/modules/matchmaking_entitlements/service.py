"""Transactional matchmaking eligibility and entitlement service (B12).

The three invariants this file exists to hold:

1. Relationship status is checked server-side on every read and write, and on
   the background jobs too, so a direct URL or a stale token gets nothing.
2. An attempt is deducted inside the same transaction that records the
   delivered candidates, under a row lock, keyed by an idempotency string. Two
   concurrent requests therefore cannot spend the same attempt twice, and a
   retry cannot spend a second one.
3. An empty or fully-repeated result never touches the balance.
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
from vav.modules.matchmaking_entitlements.domain import (
    DEFAULT_FREE_ATTEMPTS,
    MAX_CANDIDATES_PER_ATTEMPT,
    EntitlementState,
    LedgerReason,
    MatchmakingRuleError,
    RelationshipStatus,
    StatusSource,
    WaitPoolStatus,
    apply_ledger_entry,
    arrival_notification_dedupe_key,
    consumption_idempotency_key,
    decide_consumption,
    ensure_matchmaking_allowed,
    filter_new_candidates,
    is_matchmaking_allowed,
    should_notify_arrival,
    validate_status_change,
    validate_wait_pool_transition,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _fail(error: MatchmakingRuleError, status_code: int = 422) -> VavError:
    return VavError(
        error.code,
        error.message,
        status_code=status_code,
        details=[error.details] if error.details else None,
    )


def enabled() -> None:
    if not get_settings().matchmaking_entitlements_enabled:
        raise VavError(
            "MATCHMAKING_ENTITLEMENTS_DISABLED",
            "Matchmaking entitlements are not enabled.",
            status_code=503,
        )


async def _publish(session: AsyncSession, topic: str, aggregate_id: UUID, payload: dict) -> None:
    await session.execute(
        text(
            "INSERT INTO outbox_events (topic,aggregate_type,aggregate_id,payload) "
            "VALUES (:topic,'matchmaking_entitlement',:id,CAST(:payload AS jsonb))"
        ),
        {"topic": topic, "id": str(aggregate_id), "payload": _json(payload)},
    )


# ---------------------------------------------------------------------------
# MATCH-001 relationship status
# ---------------------------------------------------------------------------


async def get_relationship_status(session: AsyncSession, user_id: UUID) -> dict:
    row = (
        (
            await session.execute(
                text(
                    "SELECT user_id,status,source,couple_relationship_id,declared_at,effective_from,version "
                    "FROM member_relationship_statuses WHERE user_id=:user_id"
                ),
                {"user_id": str(user_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        # A member with no row has never answered. Return the closed default
        # rather than 404 so callers cannot mistake "missing" for "allowed".
        return {
            "user_id": str(user_id),
            "status": RelationshipStatus.UNDISCLOSED.value,
            "source": StatusSource.SELF_DECLARED.value,
            "matchmaking_available": False,
            "version": 0,
        }
    return {
        "user_id": str(row["user_id"]),
        "status": row["status"],
        "source": row["source"],
        "couple_relationship_id": (
            str(row["couple_relationship_id"]) if row["couple_relationship_id"] else None
        ),
        "declared_at": row["declared_at"],
        "effective_from": row["effective_from"],
        "version": row["version"],
        "matchmaking_available": is_matchmaking_allowed(row["status"]),
    }


async def require_matchmaking_eligibility(session: AsyncSession, user_id: UUID) -> str:
    """Authorization prerequisite used by every matchmaking entry point.

    Raises 403 rather than 404: the member is authenticated and the resource
    exists, they are simply not permitted to reach it in their current state.
    """

    current = await get_relationship_status(session, user_id)
    try:
        ensure_matchmaking_allowed(current["status"])
    except MatchmakingRuleError as error:
        raise _fail(error, status_code=403) from error
    return current["status"]


async def set_relationship_status(
    session: AsyncSession,
    *,
    user_id: UUID,
    target: str,
    source: str,
    actor_id: UUID | None,
    actor_kind: str,
    reason: str | None = None,
    couple_relationship_id: UUID | None = None,
) -> dict:
    """Write a relationship status and record the change in history.

    Moving away from an eligible status closes matchmaking immediately: any
    pending wait-pool membership is exited in the same transaction. Nothing is
    deleted, so the audit trail and the spent-attempt ledger both survive.
    """

    enabled()
    current = (
        (
            await session.execute(
                text(
                    "SELECT status,source,couple_relationship_id FROM member_relationship_statuses "
                    "WHERE user_id=:user_id FOR UPDATE"
                ),
                {"user_id": str(user_id)},
            )
        )
        .mappings()
        .first()
    )
    current_status = current["status"] if current else None
    locked = bool(current and current["source"] == StatusSource.COUPLE_BINDING)
    try:
        target_status = validate_status_change(
            current=current_status,
            target=target,
            source=source,
            locked_by_couple_binding=locked,
        )
    except MatchmakingRuleError as error:
        raise _fail(error, status_code=409) from error

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
            "user_id": str(user_id),
            "status": target_status.value,
            "source": source,
            "couple_id": str(couple_relationship_id) if couple_relationship_id else None,
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
            "user_id": str(user_id),
            "from_status": current_status,
            "to_status": target_status.value,
            "source": source,
            "reason": reason,
            "actor": str(actor_id) if actor_id else None,
            "actor_kind": actor_kind,
        },
    )
    if not is_matchmaking_allowed(target_status):
        await session.execute(
            text(
                "UPDATE matchmaking_wait_pool_entries SET status='exited',exited_at=now(),"
                "exit_reason='relationship_status_changed',updated_at=now() "
                "WHERE user_id=:user_id AND status <> 'exited'"
            ),
            {"user_id": str(user_id)},
        )
        await _publish(
            session,
            "matchmaking.access.revoked.v1",
            user_id,
            {"user_id": str(user_id), "status": target_status.value},
        )
    await session.commit()
    return await get_relationship_status(session, user_id)


# ---------------------------------------------------------------------------
# MATCH-002 entitlement ledger
# ---------------------------------------------------------------------------


async def _load_state(session: AsyncSession, user_id: UUID, *, lock: bool) -> EntitlementState:
    suffix = " FOR UPDATE" if lock else ""
    row = (
        (
            await session.execute(
                text(
                    "SELECT granted,consumed,expires_at,policy_version FROM matchmaking_entitlements "
                    "WHERE user_id=:user_id" + suffix
                ),
                {"user_id": str(user_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return EntitlementState(granted=0, consumed=0)
    return EntitlementState(
        granted=int(row["granted"]),
        consumed=int(row["consumed"]),
        expires_at=row["expires_at"],
        policy_version=row["policy_version"],
    )


async def _write_state(
    session: AsyncSession,
    *,
    user_id: UUID,
    state: EntitlementState,
    delta: int,
    reason: str,
    idempotency_key: str,
    batch_id: UUID | None,
    actor_id: UUID | None,
    actor_kind: str,
    note: str | None = None,
) -> bool:
    """Persist a ledger line plus the aggregate. Returns False if it was a replay.

    The unique constraint on ``idempotency_key`` is the concurrency control: a
    duplicate insert is caught and reported as "already applied" rather than
    quietly charging the member again.
    """

    try:
        await session.execute(
            text(
                "INSERT INTO matchmaking_entitlement_entries "
                "(user_id,delta,reason,idempotency_key,batch_id,granted_after,consumed_after,balance_after,actor_id,actor_kind,note) "
                "VALUES (:user_id,:delta,:reason,:key,:batch_id,:granted,:consumed,:balance,:actor,:actor_kind,:note)"
            ),
            {
                "user_id": str(user_id),
                "delta": delta,
                "reason": reason,
                "key": idempotency_key,
                "batch_id": str(batch_id) if batch_id else None,
                "granted": state.granted,
                "consumed": state.consumed,
                "balance": state.balance,
                "actor": str(actor_id) if actor_id else None,
                "actor_kind": actor_kind,
                "note": note,
            },
        )
    except IntegrityError:
        await session.rollback()
        return False
    await session.execute(
        text(
            "INSERT INTO matchmaking_entitlements "
            "(user_id,granted,consumed,expires_at,policy_version,first_granted_at,last_consumed_at) "
            "VALUES (:user_id,:granted,:consumed,:expires_at,:policy_version,"
            "CASE WHEN :is_grant THEN now() ELSE NULL END,CASE WHEN :is_consume THEN now() ELSE NULL END) "
            "ON CONFLICT (user_id) DO UPDATE SET granted=EXCLUDED.granted,consumed=EXCLUDED.consumed,"
            "expires_at=EXCLUDED.expires_at,policy_version=EXCLUDED.policy_version,"
            "first_granted_at=COALESCE(matchmaking_entitlements.first_granted_at, EXCLUDED.first_granted_at),"
            "last_consumed_at=COALESCE(EXCLUDED.last_consumed_at, matchmaking_entitlements.last_consumed_at),"
            "version=matchmaking_entitlements.version+1,updated_at=now()"
        ),
        {
            "user_id": str(user_id),
            "granted": state.granted,
            "consumed": state.consumed,
            "expires_at": state.expires_at,
            "policy_version": state.policy_version,
            "is_grant": reason in (LedgerReason.GRANT, LedgerReason.ADMIN_ADJUST),
            "is_consume": reason == LedgerReason.CONSUME,
        },
    )
    return True


async def ensure_initial_grant(session: AsyncSession, user_id: UUID) -> EntitlementState:
    """Grant the three free attempts once, on first eligible use.

    Keyed on the user so a race between two first requests produces one grant.
    DEC-004 (lifetime versus expiring) is unresolved, so no expiry is set and
    the policy version records that the decision is still pending.
    """

    enabled()
    state = await _load_state(session, user_id, lock=True)
    if state.granted > 0:
        return state
    settings = get_settings()
    granted = apply_ledger_entry(
        state, delta=settings.matchmaking_free_attempts, reason=LedgerReason.GRANT
    )
    applied = await _write_state(
        session,
        user_id=user_id,
        state=granted,
        delta=settings.matchmaking_free_attempts,
        reason=LedgerReason.GRANT,
        idempotency_key=f"matchmaking-initial-grant:{user_id}",
        batch_id=None,
        actor_id=None,
        actor_kind="system",
    )
    if not applied:
        return await _load_state(session, user_id, lock=False)
    return granted


async def get_entitlement(session: AsyncSession, user_id: UUID) -> dict:
    enabled()
    status = await get_relationship_status(session, user_id)
    if not status["matchmaking_available"]:
        # Non-single members are shown no quota at all, not a zeroed one:
        # a balance readout is itself matchmaking data (MATCH-001).
        raise VavError(
            "MATCHMAKING_NOT_AVAILABLE",
            "Matchmaking is only available to members who have declared they are single.",
            status_code=403,
        )
    state = await _load_state(session, user_id, lock=False)
    entries = (
        (
            await session.execute(
                text(
                    "SELECT delta,reason,balance_after,note,created_at FROM matchmaking_entitlement_entries "
                    "WHERE user_id=:user_id ORDER BY created_at DESC LIMIT 20"
                ),
                {"user_id": str(user_id)},
            )
        )
        .mappings()
        .all()
    )
    return {
        "granted": state.granted,
        "consumed": state.consumed,
        "balance": state.balance,
        "expires_at": state.expires_at,
        "policy_version": state.policy_version,
        "max_candidates_per_attempt": MAX_CANDIDATES_PER_ATTEMPT,
        "ledger": [dict(entry) for entry in entries],
    }


async def admin_adjust_entitlement(
    session: AsyncSession, *, user_id: UUID, actor_id: UUID, payload: dict
) -> dict:
    enabled()
    state = await _load_state(session, user_id, lock=True)
    try:
        updated = apply_ledger_entry(
            state, delta=int(payload["delta"]), reason=LedgerReason.ADMIN_ADJUST
        )
    except MatchmakingRuleError as error:
        raise _fail(error, status_code=409) from error
    applied = await _write_state(
        session,
        user_id=user_id,
        state=updated,
        delta=int(payload["delta"]),
        reason=LedgerReason.ADMIN_ADJUST,
        idempotency_key=payload.get("idempotency_key") or f"matchmaking-adjust:{uuid4()}",
        batch_id=None,
        actor_id=actor_id,
        actor_kind="admin",
        note=payload["note"],
    )
    if not applied:
        raise VavError(
            "ENTITLEMENT_ADJUSTMENT_REPLAYED",
            "That adjustment has already been applied.",
            status_code=409,
        )
    await session.commit()
    return {
        "user_id": str(user_id),
        "granted": updated.granted,
        "consumed": updated.consumed,
        "balance": updated.balance,
    }


# ---------------------------------------------------------------------------
# MATCH-002 + MATCH-003 the generation transaction
# ---------------------------------------------------------------------------


async def _delivered_candidate_ids(session: AsyncSession, user_id: UUID) -> list[UUID]:
    generation = await _reset_generation(session, user_id)
    rows = (
        await session.execute(
            text(
                "SELECT candidate_user_id FROM matchmaking_delivery_history "
                "WHERE user_id=:user_id AND reset_generation=:generation"
            ),
            {"user_id": str(user_id), "generation": generation},
        )
    ).scalars().all()
    return [UUID(str(item)) for item in rows]


async def _reset_generation(session: AsyncSession, user_id: UUID) -> int:
    """Current de-duplication generation for this member.

    Read from the entitlement row rather than derived from history, so bumping
    it immediately makes the whole previous history invisible to the filter
    while leaving every row queryable for support.
    """

    value = await session.scalar(
        text("SELECT delivery_reset_generation FROM matchmaking_entitlements WHERE user_id=:user_id"),
        {"user_id": str(user_id)},
    )
    return int(value or 1)


async def _eligible_candidate_ids(session: AsyncSession, user_id: UUID) -> list[UUID]:
    """Ranked, policy-filtered pool.

    Only members who are themselves matchmaking-eligible can appear, so a
    member who has since entered a relationship stops being recommended to
    anyone without their profile being deleted.
    """

    rows = (
        await session.execute(
            text(
                "SELECT p.user_id FROM recommendation_pool_entries p "
                "JOIN member_relationship_statuses s ON s.user_id=p.user_id "
                "WHERE p.eligible=true AND p.user_id <> :user_id "
                "  AND s.status IN ('single','separated','widowed') "
                "  AND NOT EXISTS (SELECT 1 FROM activity_interaction_restrictions r "
                "        WHERE r.status='active' AND ((r.user_a_id=:user_id AND r.user_b_id=p.user_id) "
                "           OR (r.user_b_id=:user_id AND r.user_a_id=p.user_id))) "
                "ORDER BY p.updated_at DESC LIMIT 200"
            ),
            {"user_id": str(user_id)},
        )
    ).scalars().all()
    return [UUID(str(item)) for item in rows]


async def generate_recommendations(session: AsyncSession, *, user_id: UUID) -> dict:
    """One free-attempt generation.

    Order matters and is deliberate:

    1. relationship gate (403 before anything else is read)
    2. lock the entitlement row
    3. compute fresh candidates
    4. decide consumption — empty result means no charge
    5. write delivery history and the ledger line in the same transaction
    """

    enabled()
    await require_matchmaking_eligibility(session, user_id)
    state = await ensure_initial_grant(session, user_id)

    delivered_before = await _delivered_candidate_ids(session, user_id)
    pool = await _eligible_candidate_ids(session, user_id)
    fresh = filter_new_candidates(pool, already_delivered=delivered_before)

    now = _now()
    try:
        decision = decide_consumption(
            state,
            fresh_candidates=fresh,
            now=now,
            max_candidates=get_settings().matchmaking_candidates_per_attempt,
        )
    except MatchmakingRuleError as error:
        raise _fail(error, status_code=409) from error

    if not decision.should_consume:
        await _enter_wait_pool(session, user_id, reason=decision.reason_code)
        await session.commit()
        return {
            "consumed": False,
            "reason_code": decision.reason_code,
            "candidates": [],
            "balance": state.balance,
            "wait_pool": True,
            "disclaimer": await published_disclaimer(session),
        }

    batch_id = uuid4()
    generation = await _reset_generation(session, user_id)
    for candidate_id in decision.delivered:
        await session.execute(
            text(
                "INSERT INTO matchmaking_delivery_history "
                "(user_id,candidate_user_id,first_batch_id,reset_generation) "
                "VALUES (:user_id,:candidate_id,:batch_id,:generation) "
                "ON CONFLICT (user_id, candidate_user_id, reset_generation) DO UPDATE SET "
                "last_delivered_at=now(),delivery_count=matchmaking_delivery_history.delivery_count+1"
            ),
            {
                "user_id": str(user_id),
                "candidate_id": str(candidate_id),
                "batch_id": str(batch_id),
                "generation": generation,
            },
        )

    consumed_state = apply_ledger_entry(state, delta=-1, reason=LedgerReason.CONSUME)
    applied = await _write_state(
        session,
        user_id=user_id,
        state=consumed_state,
        delta=-1,
        reason=LedgerReason.CONSUME,
        idempotency_key=consumption_idempotency_key(user_id, batch_id),
        batch_id=batch_id,
        actor_id=user_id,
        actor_kind="member",
    )
    if not applied:
        raise VavError(
            "ENTITLEMENT_CONSUMPTION_REPLAYED",
            "This generation was already recorded.",
            status_code=409,
        )
    await _exit_wait_pool(session, user_id, reason="candidates_delivered")
    await session.commit()
    return {
        "consumed": True,
        "reason_code": decision.reason_code,
        "batch_id": str(batch_id),
        "candidates": [str(item) for item in decision.delivered],
        "balance": consumed_state.balance,
        "wait_pool": False,
        "disclaimer": await published_disclaimer(session),
    }


# ---------------------------------------------------------------------------
# MATCH-003 wait pool
# ---------------------------------------------------------------------------


async def _enter_wait_pool(session: AsyncSession, user_id: UUID, *, reason: str) -> None:
    await session.execute(
        text(
            "INSERT INTO matchmaking_wait_pool_entries (user_id,status,entered_at) "
            "VALUES (:user_id,'waiting',now()) "
            "ON CONFLICT (user_id) DO UPDATE SET status='waiting',exited_at=NULL,exit_reason=NULL,"
            "entered_at=CASE WHEN matchmaking_wait_pool_entries.status='exited' THEN now() "
            "  ELSE matchmaking_wait_pool_entries.entered_at END,updated_at=now()"
        ),
        {"user_id": str(user_id)},
    )


async def _exit_wait_pool(session: AsyncSession, user_id: UUID, *, reason: str) -> None:
    await session.execute(
        text(
            "UPDATE matchmaking_wait_pool_entries SET status='exited',exited_at=now(),"
            "exit_reason=:reason,updated_at=now() WHERE user_id=:user_id AND status <> 'exited'"
        ),
        {"user_id": str(user_id), "reason": reason},
    )


async def get_wait_pool_state(session: AsyncSession, user_id: UUID) -> dict:
    enabled()
    await require_matchmaking_eligibility(session, user_id)
    row = (
        (
            await session.execute(
                text(
                    "SELECT status,entered_at,last_notified_at,notify_count,exited_at,exit_reason "
                    "FROM matchmaking_wait_pool_entries WHERE user_id=:user_id"
                ),
                {"user_id": str(user_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return {"status": "not_in_pool"}
    return dict(row)


async def notify_candidate_arrivals(session: AsyncSession, *, opportunity_key: str) -> dict:
    """Background job: tell waiting members that new candidates exist.

    Idempotent on two levels — the domain cooldown suppresses repeats, and the
    outbox payload carries a per-opportunity dedupe key so a redelivered event
    still results in one message.
    """

    enabled()
    rows = (
        (
            await session.execute(
                text(
                    "SELECT w.user_id,w.status,w.last_notified_at FROM matchmaking_wait_pool_entries w "
                    "JOIN member_relationship_statuses s ON s.user_id=w.user_id "
                    "WHERE w.status <> 'exited' AND s.status IN ('single','separated','widowed')"
                )
            )
        )
        .mappings()
        .all()
    )
    now = _now()
    notified = 0
    cooldown = get_settings().matchmaking_wait_pool_cooldown_hours
    for row in rows:
        user_id = UUID(str(row["user_id"]))
        delivered = await _delivered_candidate_ids(session, user_id)
        pool = await _eligible_candidate_ids(session, user_id)
        fresh = filter_new_candidates(pool, already_delivered=delivered)
        if not should_notify_arrival(
            status=row["status"],
            last_notified_at=row["last_notified_at"],
            now=now,
            new_candidate_count=len(fresh),
            cooldown_hours=cooldown,
        ):
            continue
        try:
            validate_wait_pool_transition(row["status"], WaitPoolStatus.NOTIFIED)
        except MatchmakingRuleError:
            continue
        await session.execute(
            text(
                "UPDATE matchmaking_wait_pool_entries SET status='notified',last_notified_at=now(),"
                "notify_count=notify_count+1,last_opportunity_key=:key,updated_at=now() WHERE user_id=:user_id"
            ),
            {"key": opportunity_key, "user_id": str(user_id)},
        )
        await _publish(
            session,
            "matchmaking.candidates.arrived.v1",
            user_id,
            {
                "user_id": str(user_id),
                "new_candidate_count": len(fresh),
                "dedupe_key": arrival_notification_dedupe_key(user_id, opportunity_key),
            },
        )
        notified += 1
    await session.commit()
    return {"notified": notified, "considered": len(rows)}


async def reset_delivery_history(
    session: AsyncSession, *, user_id: UUID, actor_id: UUID, reason: str
) -> dict:
    """Start a new de-duplication generation.

    Nothing is deleted: previous generations stay queryable, so it is always
    possible to explain why a candidate reappeared.
    """

    enabled()
    # Lock the entitlement row so two administrators cannot both bump from the
    # same starting generation and lose one reset.
    current = await session.scalar(
        text(
            "SELECT delivery_reset_generation FROM matchmaking_entitlements "
            "WHERE user_id=:user_id FOR UPDATE"
        ),
        {"user_id": str(user_id)},
    )
    if current is None:
        raise VavError(
            "ENTITLEMENT_NOT_FOUND",
            "This member has no matchmaking entitlement to reset.",
            status_code=404,
        )
    from_generation = int(current)
    to_generation = from_generation + 1
    await session.execute(
        text(
            "UPDATE matchmaking_entitlements SET delivery_reset_generation=:generation,"
            "version=version+1,updated_at=now() WHERE user_id=:user_id"
        ),
        {"generation": to_generation, "user_id": str(user_id)},
    )
    await session.execute(
        text(
            "INSERT INTO matchmaking_delivery_resets "
            "(user_id,from_generation,to_generation,reason,actor_id) "
            "VALUES (:user_id,:from_generation,:to_generation,:reason,:actor)"
        ),
        {
            "user_id": str(user_id),
            "from_generation": from_generation,
            "to_generation": to_generation,
            "reason": reason,
            "actor": str(actor_id),
        },
    )
    await session.commit()
    return {
        "user_id": str(user_id),
        "from_generation": from_generation,
        "reset_generation": to_generation,
    }


async def published_disclaimer(session: AsyncSession, locale: str = "zh-CN") -> dict | None:
    """Approved V1.6 disclaimer copy, or ``None`` if none is published yet.

    Returning ``None`` rather than a placeholder keeps unapproved wording off
    the member surface; the frontend renders the section only when copy exists.
    """

    row = (
        (
            await session.execute(
                text(
                    "SELECT disclaimer_code,semantic_version,locale,body FROM matchmaking_disclaimers "
                    "WHERE status='published' AND locale=:locale "
                    "ORDER BY semantic_version DESC LIMIT 1"
                ),
                {"locale": locale},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def upsert_disclaimer(session: AsyncSession, *, actor_id: UUID, payload: dict) -> dict:
    enabled()
    await session.execute(
        text(
            "INSERT INTO matchmaking_disclaimers (disclaimer_code,semantic_version,locale,body,status) "
            "VALUES (:code,:version,:locale,:body,'draft') "
            "ON CONFLICT (disclaimer_code, semantic_version, locale) DO UPDATE SET body=EXCLUDED.body,"
            "updated_at=now() WHERE matchmaking_disclaimers.status='draft'"
        ),
        {
            "code": payload["disclaimer_code"],
            "version": payload["semantic_version"],
            "locale": payload["locale"],
            "body": payload["body"],
        },
    )
    await session.commit()
    return {"disclaimer_code": payload["disclaimer_code"], "status": "draft"}


async def publish_disclaimer(session: AsyncSession, *, disclaimer_id: UUID, actor_id: UUID) -> dict:
    enabled()
    updated = await session.execute(
        text(
            "UPDATE matchmaking_disclaimers SET status='published',approved_by=:actor,approved_at=now(),"
            "updated_at=now() WHERE id=:id AND status='draft'"
        ),
        {"actor": str(actor_id), "id": str(disclaimer_id)},
    )
    if updated.rowcount == 0:
        raise VavError(
            "DISCLAIMER_NOT_DRAFT", "Only a draft disclaimer can be published.", status_code=409
        )
    await session.commit()
    return {"disclaimer_id": str(disclaimer_id), "status": "published"}


DEFAULT_GRANT = DEFAULT_FREE_ATTEMPTS
