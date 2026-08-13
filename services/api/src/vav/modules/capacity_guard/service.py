"""Transactional capacity and waitlist-promotion service (B06 / ACT-003).

Design notes:

* Every seat decision runs **inside** a row lock on
  ``activity_capacity_counters``. The lock is taken before the counts are read,
  not after they are compared, so the check and the write are one critical
  section. A read-then-write - "count the confirmed rows, decide, insert" -
  oversells the moment two members press the button in the same millisecond,
  and no amount of retrying fixes it.
* The counter row is a cache with a guard: migration ``20260812_0106`` puts a
  CHECK constraint on it, so even a code path that forgets the lock cannot
  write an oversold row - it gets an IntegrityError instead of a full room.
* Waitlist promotion order is computed by the pure domain, so the same queue
  produces the same promotions on any replica.
* All business rules live in :mod:`vav.modules.capacity_guard.domain`.
"""

# ruff: noqa: E501

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.capacity_guard.domain import (
    CapacityRuleError,
    CapacitySnapshot,
    FitOutcome,
    OfferResponse,
    OfferState,
    PromotionOffer,
    SalesState,
    WaitlistEntry,
    WaitlistStatus,
    apply_seat_grant,
    apply_seat_release,
    clamp_offer_deadline,
    confirm_held_seats,
    ensure_not_oversold,
    evaluate_fit,
    expire_offer,
    is_promotion_offer_expired,
    is_unlimited,
    ordered_waitlist,
    plan_promotions_after_release,
    promotion_dedupe_key,
    resolve_offer_response,
    validate_waitlist_transition,
    waitlist_position,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _fail(error: CapacityRuleError, status_code: int = 422) -> VavError:
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


def capacity_guard_enabled() -> None:
    if not get_settings().capacity_guard_enabled:
        raise VavError(
            "CAPACITY_GUARD_DISABLED",
            "Transactional capacity enforcement is not enabled.",
            status_code=503,
        )


def waitlist_enabled() -> bool:
    return bool(get_settings().waitlist_promotion_enabled)


async def _publish(
    session: AsyncSession,
    topic: str,
    aggregate_type: str,
    aggregate_id: UUID,
    payload: dict[str, Any],
) -> None:
    await session.execute(
        text(
            "INSERT INTO outbox_events (topic,aggregate_type,aggregate_id,payload) "
            "VALUES (:topic,:aggregate_type,:id,CAST(:payload AS jsonb))"
        ),
        {
            "topic": topic,
            "aggregate_type": aggregate_type,
            "id": str(aggregate_id),
            "payload": _json(payload),
        },
    )


async def _record_event(
    session: AsyncSession,
    *,
    activity_id: UUID,
    ticket_type_id: UUID,
    registration_id: UUID | None,
    event_type: str,
    seats: int,
    actor_id: UUID | None,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO activity_capacity_events "
            "(id,activity_id,ticket_type_id,registration_id,event_type,seats,actor_id,reason,metadata) "
            "VALUES (:id,:activity_id,:ticket_type_id,:registration_id,:event_type,:seats,:actor_id,:reason,CAST(:metadata AS jsonb))"
        ),
        {
            "id": str(uuid4()),
            "activity_id": str(activity_id),
            "ticket_type_id": str(ticket_type_id),
            "registration_id": str(registration_id) if registration_id else None,
            "event_type": event_type,
            "seats": seats,
            "actor_id": str(actor_id) if actor_id else None,
            "reason": reason,
            "metadata": _json(metadata or {}),
        },
    )


# ---------------------------------------------------------------------------
# The critical section
# ---------------------------------------------------------------------------


async def _lock_counter(session: AsyncSession, ticket_type_id: UUID) -> dict[str, Any]:
    """Take the row lock, then read. Never the other way around.

    ``FOR UPDATE`` on the counter row is the whole concurrency design: every
    seat transition for one ticket type serializes behind it. The counter is
    also the *only* row that needs locking, so two different ticket types on the
    same activity never block each other and the door does not queue up.
    """

    async def load() -> Any:
        return (
            (
                await session.execute(
                    text(
                        "SELECT ticket_type_id,activity_id,capacity,confirmed_seats,held_seats,"
                        "waitlisted_count,waitlist_capacity,sales_state,version "
                        "FROM activity_capacity_counters WHERE ticket_type_id=:id FOR UPDATE"
                    ),
                    {"id": str(ticket_type_id)},
                )
            )
            .mappings()
            .first()
        )

    row = await load()
    if row is None:
        # Ticket types may be created after the migration backfill. Lazily
        # create their counter from the catalogue inside the same transaction,
        # then lock it. ON CONFLICT makes concurrent first registrations safe.
        await session.execute(
            text(
                "INSERT INTO activity_capacity_counters "
                "(ticket_type_id,activity_id,capacity) "
                "SELECT t.id,t.activity_id,"
                "CASE WHEN s.inventory_policy='unlimited' THEN 0 ELSE "
                "GREATEST(0,COALESCE(i.total_capacity,0)-COALESCE(i.safety_stock,0)+"
                "CASE WHEN COALESCE(i.overselling_allowed,false) "
                "THEN COALESCE(i.oversell_limit,0) ELSE 0 END) END "
                "FROM activity_ticket_types t "
                "JOIN product_skus s ON s.id=t.catalog_sku_id "
                "LEFT JOIN inventory_items i ON i.sku_id=s.id "
                "WHERE t.id=:id ON CONFLICT (ticket_type_id) DO NOTHING"
            ),
            {"id": str(ticket_type_id)},
        )
        row = await load()
    if row is None:
        raise VavError(
            "CAPACITY_COUNTER_MISSING",
            "This ticket type has no capacity counter; run the backfill in migration 20260812_0106.",
            status_code=409,
            details=[{"ticket_type_id": str(ticket_type_id)}],
        )
    return dict(row)


def _snapshot(row: dict[str, Any]) -> CapacitySnapshot:
    return CapacitySnapshot(
        capacity=int(row["capacity"]),
        confirmed_seats=int(row["confirmed_seats"]),
        held_seats=int(row["held_seats"]),
        waitlisted_count=int(row["waitlisted_count"]),
        waitlist_capacity=(
            int(row["waitlist_capacity"]) if row["waitlist_capacity"] is not None else None
        ),
        sales_state=SalesState(str(row["sales_state"])),
    )


async def _write_counter(
    session: AsyncSession,
    *,
    ticket_type_id: UUID,
    snapshot: CapacitySnapshot,
    expected_version: int,
) -> None:
    """Persist the transition, with the version as a second line of defence.

    The row lock already serializes writers. The version predicate catches the
    other bug: a caller that computed the snapshot from a row it read *before*
    taking the lock. That write simply does not apply, and the mismatch is
    raised rather than swallowed.
    """

    result = cast(
        CursorResult[Any],
        await session.execute(
            text(
                "UPDATE activity_capacity_counters SET capacity=:capacity,confirmed_seats=:confirmed,"
                "held_seats=:held,waitlisted_count=:waitlisted,waitlist_capacity=:waitlist_capacity,"
                "sales_state=:sales_state,version=version+1,updated_at=now() "
                "WHERE ticket_type_id=:id AND version=:expected_version"
            ),
            {
                "capacity": snapshot.capacity,
                "confirmed": snapshot.confirmed_seats,
                "held": snapshot.held_seats,
                "waitlisted": snapshot.waitlisted_count,
                "waitlist_capacity": snapshot.waitlist_capacity,
                "sales_state": snapshot.sales_state.value,
                "id": str(ticket_type_id),
                "expected_version": expected_version,
            },
        ),
    )
    if result.rowcount != 1:
        raise VavError(
            "CAPACITY_COUNTER_CONFLICT",
            "The capacity counter changed underneath this transaction; retry.",
            status_code=409,
        )


# ---------------------------------------------------------------------------
# ACT-003 seat reservation
# ---------------------------------------------------------------------------


async def reserve_seat(
    session: AsyncSession,
    *,
    ticket_type_id: UUID,
    registration_id: UUID,
    user_id: UUID,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Take a held seat, or a place in the queue, or refuse. Atomically.

    Returns the same outcome for a retried ``idempotency_key`` rather than
    taking a second seat: a member who double-taps on a flaky connection is the
    common case, and charging them two seats for it is not acceptable.
    """

    capacity_guard_enabled()
    seats = int(payload.get("seats") or 1)
    idempotency_key = str(payload["idempotency_key"])

    existing = (
        (
            await session.execute(
                text(
                    "SELECT registration_id,outcome,seats,waitlist_entry_id "
                    "FROM activity_capacity_reservations "
                    "WHERE idempotency_key=:key"
                ),
                {"key": idempotency_key},
            )
        )
        .mappings()
        .first()
    )
    if existing is not None:
        if UUID(str(existing["registration_id"])) != registration_id:
            raise VavError(
                "CAPACITY_IDEMPOTENCY_KEY_REUSED",
                "This idempotency key belongs to a different registration.",
                status_code=409,
            )
        return {
            "outcome": existing["outcome"],
            "seats": int(existing["seats"]),
            "waitlist_entry_id": (
                str(existing["waitlist_entry_id"]) if existing["waitlist_entry_id"] else None
            ),
            "idempotent_replay": True,
        }

    row = await _lock_counter(session, ticket_type_id)
    activity_id = UUID(str(row["activity_id"]))
    snapshot = _snapshot(row)
    try:
        decision = evaluate_fit(
            snapshot,
            requested_seats=seats,
            waitlist_enabled=waitlist_enabled() and bool(payload.get("accept_waitlist", True)),
        )
    except CapacityRuleError as error:
        raise _fail(error, status_code=409) from error

    waitlist_entry_id: UUID | None = None
    if decision.outcome is FitOutcome.FITS:
        if not is_unlimited(snapshot):
            updated = apply_seat_grant(snapshot, seats=seats, hold=True)
            await _write_counter(
                session,
                ticket_type_id=ticket_type_id,
                snapshot=updated,
                expected_version=int(row["version"]),
            )
        await _record_event(
            session,
            activity_id=activity_id,
            ticket_type_id=ticket_type_id,
            registration_id=registration_id,
            event_type="seat_held",
            seats=seats,
            actor_id=user_id,
        )
        await _publish(
            session,
            "activity.capacity.seat_held.v1",
            "activity_registration",
            registration_id,
            {"ticket_type_id": str(ticket_type_id), "seats": seats},
        )
    elif decision.outcome is FitOutcome.WAITLIST:
        waitlist_entry_id = uuid4()
        updated = CapacitySnapshot(
            capacity=snapshot.capacity,
            confirmed_seats=snapshot.confirmed_seats,
            held_seats=snapshot.held_seats,
            waitlisted_count=snapshot.waitlisted_count + 1,
            waitlist_capacity=snapshot.waitlist_capacity,
            sales_state=snapshot.sales_state,
        )
        await _write_counter(
            session,
            ticket_type_id=ticket_type_id,
            snapshot=updated,
            expected_version=int(row["version"]),
        )
        await session.execute(
            text(
                "INSERT INTO activity_waitlist_positions "
                "(id,activity_id,ticket_type_id,registration_id,user_id,seats,priority,status,joined_at) "
                "VALUES (:id,:activity_id,:ticket_type_id,:registration_id,:user_id,:seats,0,'waiting',:joined_at)"
            ),
            {
                "id": str(waitlist_entry_id),
                "activity_id": str(activity_id),
                "ticket_type_id": str(ticket_type_id),
                "registration_id": str(registration_id),
                "user_id": str(user_id),
                "seats": seats,
                "joined_at": _now(),
            },
        )
        await _publish(
            session,
            "activity.waitlist.joined.v1",
            "activity_registration",
            registration_id,
            {"ticket_type_id": str(ticket_type_id), "seats": seats},
        )
    else:
        await _record_event(
            session,
            activity_id=activity_id,
            ticket_type_id=ticket_type_id,
            registration_id=registration_id,
            event_type="refused",
            seats=seats,
            actor_id=user_id,
            reason=decision.reason_code,
        )
        raise VavError(
            decision.reason_code or "CAPACITY_FULL",
            "There is no seat available on this ticket type.",
            status_code=409,
            details=[{"ticket_type_id": str(ticket_type_id), "requested_seats": seats}],
        )

    try:
        await session.execute(
            text(
                "INSERT INTO activity_capacity_reservations "
                "(id,idempotency_key,activity_id,ticket_type_id,registration_id,user_id,seats,outcome,waitlist_entry_id) "
                "VALUES (:id,:key,:activity_id,:ticket_type_id,:registration_id,:user_id,:seats,:outcome,:waitlist_entry_id)"
            ),
            {
                "id": str(uuid4()),
                "key": idempotency_key,
                "activity_id": str(activity_id),
                "ticket_type_id": str(ticket_type_id),
                "registration_id": str(registration_id),
                "user_id": str(user_id),
                "seats": seats,
                "outcome": decision.outcome.value,
                "waitlist_entry_id": str(waitlist_entry_id) if waitlist_entry_id else None,
            },
        )
    except IntegrityError as error:
        # Two requests carrying the same key raced past the read above. The
        # unique index is the arbiter; this one loses and reports the conflict
        # rather than holding a seat nobody asked for twice.
        raise VavError(
            "CAPACITY_RESERVATION_DUPLICATE",
            "This reservation was already processed.",
            status_code=409,
        ) from error

    return {
        "outcome": decision.outcome.value,
        "seats": seats,
        "remaining_after": decision.remaining_after,
        "waitlist_entry_id": str(waitlist_entry_id) if waitlist_entry_id else None,
        "idempotent_replay": False,
    }


async def confirm_reservation(
    session: AsyncSession, *, ticket_type_id: UUID, registration_id: UUID, seats: int
) -> dict[str, Any]:
    """Move held seats to confirmed once payment or approval lands."""

    capacity_guard_enabled()
    already_confirmed = (
        await session.execute(
            text(
                "SELECT 1 FROM activity_capacity_events "
                "WHERE registration_id=:registration_id AND event_type='seat_confirmed' LIMIT 1"
            ),
            {"registration_id": str(registration_id)},
        )
    ).scalar_one_or_none()
    if already_confirmed is not None:
        return {
            "registration_id": str(registration_id),
            "confirmed_seats": seats,
            "idempotent_replay": True,
        }
    row = await _lock_counter(session, ticket_type_id)
    snapshot = _snapshot(row)
    if is_unlimited(snapshot):
        return {
            "registration_id": str(registration_id),
            "confirmed_seats": seats,
            "idempotent_replay": False,
        }
    try:
        updated = confirm_held_seats(snapshot, seats=seats)
    except CapacityRuleError as error:
        raise _fail(error, status_code=409) from error
    await _write_counter(
        session,
        ticket_type_id=ticket_type_id,
        snapshot=updated,
        expected_version=int(row["version"]),
    )
    await _record_event(
        session,
        activity_id=UUID(str(row["activity_id"])),
        ticket_type_id=ticket_type_id,
        registration_id=registration_id,
        event_type="seat_confirmed",
        seats=seats,
        actor_id=None,
    )
    return {
        "registration_id": str(registration_id),
        "confirmed_seats": updated.confirmed_seats,
        "held_seats": updated.held_seats,
        "idempotent_replay": False,
    }


async def release_seats(
    session: AsyncSession,
    *,
    ticket_type_id: UUID,
    registration_id: UUID,
    seats: int,
    from_hold: bool,
    reason: str,
    actor_id: UUID | None = None,
    promote: bool = True,
) -> dict[str, Any]:
    """Give seats back and immediately plan the next promotion round.

    Releasing and promoting happen in the same transaction and under the same
    lock. Splitting them - release now, promote from a job later - opens a
    window in which the seat exists but nobody can have it, which is how a
    waitlist ends up with people still queued for an event that ran half empty.
    """

    capacity_guard_enabled()
    row = await _lock_counter(session, ticket_type_id)
    activity_id = UUID(str(row["activity_id"]))
    snapshot = _snapshot(row)
    if is_unlimited(snapshot):
        return {"released": 0, "promotions": []}
    try:
        updated = apply_seat_release(snapshot, seats=seats, from_hold=from_hold)
    except CapacityRuleError as error:
        raise _fail(error, status_code=409) from error
    await _write_counter(
        session,
        ticket_type_id=ticket_type_id,
        snapshot=updated,
        expected_version=int(row["version"]),
    )
    await _record_event(
        session,
        activity_id=activity_id,
        ticket_type_id=ticket_type_id,
        registration_id=registration_id,
        event_type="seat_released",
        seats=seats,
        actor_id=actor_id,
        reason=reason,
    )
    await _publish(
        session,
        "activity.capacity.seat_released.v1",
        "activity_registration",
        registration_id,
        {"ticket_type_id": str(ticket_type_id), "seats": seats, "reason": reason},
    )
    promotions: dict[str, Any] = {"offers": []}
    if promote:
        promotions = await _run_promotion_round_locked(
            session,
            ticket_type_id=ticket_type_id,
            activity_id=activity_id,
            counter_row={**row, "version": int(row["version"]) + 1},
            snapshot=updated,
            allow_skip_oversized=bool(get_settings().waitlist_allow_skip_oversized),
            max_offers=int(get_settings().waitlist_promotion_batch_size),
            dry_run=False,
        )
    return {"released": seats, "promotions": promotions["offers"]}


async def release_registration(
    session: AsyncSession,
    *,
    ticket_type_id: UUID,
    registration_id: UUID,
    reason: str,
    actor_id: UUID | None = None,
    promote: bool = True,
) -> dict[str, Any]:
    """Release the guard state owned by one registration exactly once."""

    capacity_guard_enabled()
    reservation = (
        (
            await session.execute(
                text(
                    "SELECT outcome,seats FROM activity_capacity_reservations "
                    "WHERE registration_id=:registration_id"
                ),
                {"registration_id": str(registration_id)},
            )
        )
        .mappings()
        .first()
    )
    if reservation is None:
        return {"released": 0, "promotions": [], "reservation_found": False}

    if str(reservation["outcome"]) == FitOutcome.FITS.value:
        already_released = (
            await session.execute(
                text(
                    "SELECT 1 FROM activity_capacity_events "
                    "WHERE registration_id=:registration_id AND event_type='seat_released' LIMIT 1"
                ),
                {"registration_id": str(registration_id)},
            )
        ).scalar_one_or_none()
        if already_released is not None:
            return {"released": 0, "promotions": [], "idempotent_replay": True}
        confirmed = (
            await session.execute(
                text(
                    "SELECT 1 FROM activity_capacity_events "
                    "WHERE registration_id=:registration_id AND event_type='seat_confirmed' LIMIT 1"
                ),
                {"registration_id": str(registration_id)},
            )
        ).scalar_one_or_none()
        return await release_seats(
            session,
            ticket_type_id=ticket_type_id,
            registration_id=registration_id,
            seats=int(reservation["seats"]),
            from_hold=confirmed is None,
            reason=reason,
            actor_id=actor_id,
            promote=promote,
        )

    row = await _lock_counter(session, ticket_type_id)
    position = (
        (
            await session.execute(
                text(
                    "SELECT id,status,seats FROM activity_waitlist_positions "
                    "WHERE registration_id=:registration_id FOR UPDATE"
                ),
                {"registration_id": str(registration_id)},
            )
        )
        .mappings()
        .first()
    )
    if position is None or str(position["status"]) in {"withdrawn", "declined"}:
        return {"released": 0, "promotions": [], "idempotent_replay": True}

    snapshot = _snapshot(row)
    position_status = str(position["status"])
    had_held_seat = position_status in {
        WaitlistStatus.OFFERED.value,
        WaitlistStatus.ACCEPTED.value,
    }
    counted_in_waitlist = position_status in {
        WaitlistStatus.WAITING.value,
        WaitlistStatus.OFFERED.value,
    }
    working = snapshot
    if had_held_seat and not is_unlimited(snapshot):
        working = apply_seat_release(working, seats=int(position["seats"]), from_hold=True)
    working = CapacitySnapshot(
        capacity=working.capacity,
        confirmed_seats=working.confirmed_seats,
        held_seats=working.held_seats,
        waitlisted_count=max(
            0, working.waitlisted_count - (1 if counted_in_waitlist else 0)
        ),
        waitlist_capacity=working.waitlist_capacity,
        sales_state=working.sales_state,
    )
    await _write_counter(
        session,
        ticket_type_id=ticket_type_id,
        snapshot=working,
        expected_version=int(row["version"]),
    )
    resolved_at = _now()
    await session.execute(
        text(
            "UPDATE activity_waitlist_positions SET status='withdrawn',resolved_at=:now,"
            "version=version+1,updated_at=now() WHERE id=:id"
        ),
        {"now": resolved_at, "id": str(position["id"])},
    )
    await session.execute(
        text(
            "UPDATE activity_waitlist_promotion_offers SET state='cancelled',responded_at=:now "
            "WHERE waitlist_entry_id=:entry_id AND state='pending'"
        ),
        {"now": resolved_at, "entry_id": str(position["id"])},
    )
    offers: list[dict[str, Any]] = []
    if had_held_seat and promote:
        promotion = await _run_promotion_round_locked(
            session,
            ticket_type_id=ticket_type_id,
            activity_id=UUID(str(row["activity_id"])),
            counter_row={**row, "version": int(row["version"]) + 1},
            snapshot=working,
            allow_skip_oversized=bool(get_settings().waitlist_allow_skip_oversized),
            max_offers=int(get_settings().waitlist_promotion_batch_size),
            dry_run=False,
        )
        offers = promotion["offers"]
    return {
        "released": int(position["seats"]) if had_held_seat else 0,
        "promotions": offers,
    }


# ---------------------------------------------------------------------------
# ACT-003 waitlist promotion
# ---------------------------------------------------------------------------


async def _load_waitlist(
    session: AsyncSession, ticket_type_id: UUID
) -> tuple[list[WaitlistEntry], dict[UUID, UUID]]:
    """Active queue entries plus a registration-id -> entry-id index."""

    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,registration_id,user_id,seats,priority,status,joined_at "
                    "FROM activity_waitlist_positions "
                    "WHERE ticket_type_id=:id AND status IN ('waiting','offered') "
                    "ORDER BY priority DESC, joined_at ASC, registration_id ASC"
                ),
                {"id": str(ticket_type_id)},
            )
        )
        .mappings()
        .all()
    )
    entries = [
        WaitlistEntry(
            registration_id=UUID(str(row["registration_id"])),
            user_id=UUID(str(row["user_id"])),
            joined_at=row["joined_at"],
            seats=int(row["seats"]),
            priority=int(row["priority"]),
            status=str(row["status"]),
        )
        for row in rows
    ]
    index = {UUID(str(row["registration_id"])): UUID(str(row["id"])) for row in rows}
    return entries, index


async def _next_round_number(session: AsyncSession, ticket_type_id: UUID) -> int:
    value = (
        await session.execute(
            text(
                "SELECT COALESCE(max(round_number),0) FROM activity_waitlist_promotion_offers "
                "WHERE ticket_type_id=:id"
            ),
            {"id": str(ticket_type_id)},
        )
    ).scalar_one()
    return int(value) + 1


async def _run_promotion_round_locked(
    session: AsyncSession,
    *,
    ticket_type_id: UUID,
    activity_id: UUID,
    counter_row: dict[str, Any],
    snapshot: CapacitySnapshot,
    allow_skip_oversized: bool,
    max_offers: int,
    dry_run: bool,
) -> dict[str, Any]:
    """Plan and write one promotion round. Caller must already hold the lock."""

    if not waitlist_enabled():
        return {"offers": [], "seats_offered": 0, "blocked_by_party_size": False}
    entries, index = await _load_waitlist(session, ticket_type_id)
    try:
        plan = plan_promotions_after_release(
            snapshot,
            entries,
            allow_skip_oversized=allow_skip_oversized,
            max_offers=max_offers,
        )
    except CapacityRuleError as error:
        raise _fail(error, status_code=409) from error
    if dry_run or not plan.promotions:
        return {
            "offers": [
                {"registration_id": str(entry.registration_id), "seats": entry.seats}
                for entry in plan.promotions
            ],
            "seats_offered": plan.seats_offered,
            "blocked_by_party_size": plan.blocked_by_party_size,
            "dry_run": dry_run,
        }

    now = _now()
    round_number = await _next_round_number(session, ticket_type_id)
    ttl_minutes = int(get_settings().waitlist_promotion_ttl_minutes)
    starts_at = (
        await session.execute(
            text("SELECT starts_at FROM activities WHERE id=:id"), {"id": str(activity_id)}
        )
    ).scalar_one_or_none()

    offers: list[dict[str, Any]] = []
    working = snapshot
    for entry in plan.promotions:
        try:
            expires_at = clamp_offer_deadline(
                now, ttl_minutes=ttl_minutes, event_starts_at=starts_at
            )
            working = apply_seat_grant(working, seats=entry.seats, hold=True)
            validate_waitlist_transition(WaitlistStatus.WAITING, WaitlistStatus.OFFERED)
        except CapacityRuleError as error:
            # A party that no longer fits, or an event that started while this
            # round was being planned. Stop the round rather than partially
            # promoting people whose offers cannot be honoured.
            await _record_event(
                session,
                activity_id=activity_id,
                ticket_type_id=ticket_type_id,
                registration_id=entry.registration_id,
                event_type="promotion_aborted",
                seats=entry.seats,
                actor_id=None,
                reason=error.code,
            )
            break
        offer_id = uuid4()
        await session.execute(
            text(
                "INSERT INTO activity_waitlist_promotion_offers "
                "(id,activity_id,ticket_type_id,waitlist_entry_id,registration_id,seats,round_number,"
                "offered_at,expires_at,state,dedupe_key) "
                "VALUES (:id,:activity_id,:ticket_type_id,:entry_id,:registration_id,:seats,:round_number,"
                ":offered_at,:expires_at,'pending',:dedupe_key)"
            ),
            {
                "id": str(offer_id),
                "activity_id": str(activity_id),
                "ticket_type_id": str(ticket_type_id),
                "entry_id": str(index[entry.registration_id]),
                "registration_id": str(entry.registration_id),
                "seats": entry.seats,
                "round_number": round_number,
                "offered_at": now,
                "expires_at": expires_at,
                "dedupe_key": promotion_dedupe_key(
                    registration_id=entry.registration_id, round_number=round_number
                ),
            },
        )
        await session.execute(
            text(
                "UPDATE activity_waitlist_positions SET status='offered',offered_at=:now,"
                "version=version+1,updated_at=now() WHERE id=:id"
            ),
            {"now": now, "id": str(index[entry.registration_id])},
        )
        await _publish(
            session,
            "activity.waitlist.promotion_offered.v1",
            "activity_waitlist_promotion_offer",
            offer_id,
            {
                "activity_id": str(activity_id),
                "ticket_type_id": str(ticket_type_id),
                "registration_id": str(entry.registration_id),
                "seats": entry.seats,
                "expires_at": expires_at.isoformat(),
                "round_number": round_number,
            },
        )
        offers.append(
            {
                "offer_id": str(offer_id),
                "registration_id": str(entry.registration_id),
                "seats": entry.seats,
                "expires_at": expires_at.isoformat(),
            }
        )

    if offers:
        await _write_counter(
            session,
            ticket_type_id=ticket_type_id,
            snapshot=working,
            expected_version=int(counter_row["version"]),
        )
    return {
        "offers": offers,
        "seats_offered": sum(offer["seats"] for offer in offers),
        "blocked_by_party_size": plan.blocked_by_party_size,
        "round_number": round_number,
    }


async def run_promotion_round(session: AsyncSession, *, payload: dict[str, Any]) -> dict[str, Any]:
    """Administrative entry point for a manual promotion round."""

    capacity_guard_enabled()
    ticket_type_id = UUID(str(payload["ticket_type_id"]))
    row = await _lock_counter(session, ticket_type_id)
    snapshot = _snapshot(row)
    ensure_not_oversold(snapshot)
    return await _run_promotion_round_locked(
        session,
        ticket_type_id=ticket_type_id,
        activity_id=UUID(str(row["activity_id"])),
        counter_row=row,
        snapshot=snapshot,
        allow_skip_oversized=bool(payload.get("allow_skip_oversized")),
        max_offers=int(payload.get("max_offers") or 50),
        dry_run=bool(payload.get("dry_run")),
    )


async def _load_offer(session: AsyncSession, offer_id: UUID) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,activity_id,ticket_type_id,waitlist_entry_id,registration_id,seats,"
                    "round_number,offered_at,expires_at,state FROM activity_waitlist_promotion_offers "
                    "WHERE id=:id FOR UPDATE"
                ),
                {"id": str(offer_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("PROMOTION_OFFER_NOT_FOUND", "Promotion offer not found.", status_code=404)
    return dict(row)


def _offer_from_row(row: dict[str, Any]) -> PromotionOffer:
    return PromotionOffer(
        offer_id=UUID(str(row["id"])),
        registration_id=UUID(str(row["registration_id"])),
        seats=int(row["seats"]),
        offered_at=row["offered_at"],
        expires_at=row["expires_at"],
        state=str(row["state"]),
    )


async def respond_to_offer(
    session: AsyncSession, *, offer_id: UUID, user_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Member accepts or declines a promotion offer."""

    capacity_guard_enabled()
    row = await _load_offer(session, offer_id)
    owner = (
        await session.execute(
            text("SELECT user_id FROM activity_registrations WHERE id=:id"),
            {"id": str(row["registration_id"])},
        )
    ).scalar_one_or_none()
    if owner is None or UUID(str(owner)) != user_id:
        # 404, not 403: an offer id belonging to somebody else should not be
        # confirmable as existing.
        raise VavError("PROMOTION_OFFER_NOT_FOUND", "Promotion offer not found.", status_code=404)

    now = _now()
    offer = _offer_from_row(row)
    try:
        resolution = resolve_offer_response(
            offer, response=OfferResponse(str(payload["response"])), now=now
        )
    except CapacityRuleError as error:
        raise _fail(error, status_code=409) from error

    ticket_type_id = UUID(str(row["ticket_type_id"]))
    counter = await _lock_counter(session, ticket_type_id)
    snapshot = _snapshot(counter)
    if resolution.seats_released:
        updated = apply_seat_release(snapshot, seats=resolution.seats_released, from_hold=True)
        updated = CapacitySnapshot(
            capacity=updated.capacity,
            confirmed_seats=updated.confirmed_seats,
            held_seats=updated.held_seats,
            waitlisted_count=max(0, updated.waitlisted_count - 1),
            waitlist_capacity=updated.waitlist_capacity,
            sales_state=updated.sales_state,
        )
    else:
        updated = CapacitySnapshot(
            capacity=snapshot.capacity,
            confirmed_seats=snapshot.confirmed_seats,
            held_seats=snapshot.held_seats,
            waitlisted_count=max(0, snapshot.waitlisted_count - 1),
            waitlist_capacity=snapshot.waitlist_capacity,
            sales_state=snapshot.sales_state,
        )
    await _write_counter(
        session,
        ticket_type_id=ticket_type_id,
        snapshot=updated,
        expected_version=int(counter["version"]),
    )
    await session.execute(
        text(
            "UPDATE activity_waitlist_promotion_offers SET state=:state,responded_at=:now "
            "WHERE id=:id AND state='pending'"
        ),
        {"state": resolution.state.value, "now": now, "id": str(offer_id)},
    )
    await session.execute(
        text(
            "UPDATE activity_waitlist_positions SET status=:status,resolved_at=:now,"
            "version=version+1,updated_at=now() WHERE id=:id"
        ),
        {
            "status": resolution.waitlist_status.value,
            "now": now,
            "id": str(row["waitlist_entry_id"]),
        },
    )
    if resolution.state is OfferState.DECLINED:
        # The seat this member just gave back goes straight to the next person
        # in the queue, inside this same transaction.
        await _run_promotion_round_locked(
            session,
            ticket_type_id=ticket_type_id,
            activity_id=UUID(str(row["activity_id"])),
            counter_row={**counter, "version": int(counter["version"]) + 1},
            snapshot=updated,
            allow_skip_oversized=bool(get_settings().waitlist_allow_skip_oversized),
            max_offers=int(get_settings().waitlist_promotion_batch_size),
            dry_run=False,
        )
    return {
        "offer_id": str(offer_id),
        "state": resolution.state.value,
        "seats_confirmed": resolution.seats_confirmed,
        "waitlist_status": resolution.waitlist_status.value,
    }


async def sweep_expired_offers(session: AsyncSession, *, payload: dict[str, Any]) -> dict[str, Any]:
    """Expire timed-out offers and hand their seats to the next in line.

    Every read path already treats an offer past its deadline as expired
    (:func:`~vav.modules.capacity_guard.domain.is_promotion_offer_expired`), so
    this sweep is about releasing the *held seats*, not about correctness of the
    member-facing answer. A sweeper that has not run yet cannot let somebody
    accept a stale offer.
    """

    capacity_guard_enabled()
    now = _now()
    clause = "AND ticket_type_id=:ticket_type_id" if payload.get("ticket_type_id") else ""
    params: dict[str, Any] = {"now": now, "limit": int(payload.get("limit") or 200)}
    if payload.get("ticket_type_id"):
        params["ticket_type_id"] = str(payload["ticket_type_id"])
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id FROM activity_waitlist_promotion_offers "
                    f"WHERE state='pending' AND expires_at<=:now {clause} "
                    "ORDER BY expires_at LIMIT :limit"
                ),
                params,
            )
        )
        .scalars()
        .all()
    )
    expired: list[str] = []
    for value in rows:
        offer_id = UUID(str(value))
        row = await _load_offer(session, offer_id)
        offer = _offer_from_row(row)
        if not is_promotion_offer_expired(offer, now=now) or offer.state != OfferState.PENDING:
            continue
        resolution = expire_offer(offer, now=now)
        ticket_type_id = UUID(str(row["ticket_type_id"]))
        counter = await _lock_counter(session, ticket_type_id)
        snapshot = _snapshot(counter)
        updated = apply_seat_release(snapshot, seats=resolution.seats_released, from_hold=True)
        await _write_counter(
            session,
            ticket_type_id=ticket_type_id,
            snapshot=updated,
            expected_version=int(counter["version"]),
        )
        await session.execute(
            text(
                "UPDATE activity_waitlist_promotion_offers SET state='expired',responded_at=:now "
                "WHERE id=:id AND state='pending'"
            ),
            {"now": now, "id": str(offer_id)},
        )
        await session.execute(
            text(
                "UPDATE activity_waitlist_positions SET status='waiting',offered_at=NULL,"
                "version=version+1,updated_at=now() WHERE id=:id"
            ),
            {"id": str(row["waitlist_entry_id"])},
        )
        await _publish(
            session,
            "activity.waitlist.promotion_expired.v1",
            "activity_waitlist_promotion_offer",
            offer_id,
            {
                "ticket_type_id": str(ticket_type_id),
                "registration_id": str(row["registration_id"]),
                "seats": resolution.seats_released,
            },
        )
        await _run_promotion_round_locked(
            session,
            ticket_type_id=ticket_type_id,
            activity_id=UUID(str(row["activity_id"])),
            counter_row={**counter, "version": int(counter["version"]) + 1},
            snapshot=updated,
            allow_skip_oversized=bool(get_settings().waitlist_allow_skip_oversized),
            max_offers=int(get_settings().waitlist_promotion_batch_size),
            dry_run=False,
        )
        expired.append(str(offer_id))
    return {"expired": expired, "count": len(expired)}


# ---------------------------------------------------------------------------
# Reads and administration
# ---------------------------------------------------------------------------


async def get_capacity(session: AsyncSession, ticket_type_id: UUID) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT ticket_type_id,activity_id,capacity,confirmed_seats,held_seats,"
                    "waitlisted_count,waitlist_capacity,sales_state,version "
                    "FROM activity_capacity_counters WHERE ticket_type_id=:id"
                ),
                {"id": str(ticket_type_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError(
            "CAPACITY_COUNTER_MISSING", "This ticket type has no capacity counter.", status_code=404
        )
    snapshot = _snapshot(dict(row))
    payload = {
        "ticket_type_id": str(ticket_type_id),
        "capacity": snapshot.capacity,
        "confirmed_seats": snapshot.confirmed_seats,
        "held_seats": snapshot.held_seats,
        "waitlisted_count": snapshot.waitlisted_count,
        "sales_state": snapshot.sales_state.value,
        "unlimited": is_unlimited(snapshot),
    }
    if not is_unlimited(snapshot):
        payload["remaining_seats"] = max(0, snapshot.capacity - snapshot.taken_seats)
    return payload


async def my_waitlist_place(
    session: AsyncSession, *, ticket_type_id: UUID, registration_id: UUID
) -> dict[str, Any]:
    entries, _ = await _load_waitlist(session, ticket_type_id)
    try:
        position = waitlist_position(entries, registration_id)
    except CapacityRuleError as error:
        raise _fail(error, status_code=404) from error
    return {
        "ticket_type_id": str(ticket_type_id),
        "registration_id": str(registration_id),
        "position": position,
        "queue_length": len(ordered_waitlist(entries)),
    }


async def adjust_capacity(
    session: AsyncSession, *, ticket_type_id: UUID, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Change the cap, refusing anything that would retroactively oversell."""

    capacity_guard_enabled()
    row = await _lock_counter(session, ticket_type_id)
    snapshot = _snapshot(row)
    new_capacity = int(payload["capacity"])
    if new_capacity != 0 and new_capacity < snapshot.taken_seats:
        raise VavError(
            "CAPACITY_BELOW_CONFIRMED",
            "The new capacity is below the seats already sold or held.",
            status_code=409,
            details=[
                {
                    "requested_capacity": new_capacity,
                    "confirmed_seats": snapshot.confirmed_seats,
                    "held_seats": snapshot.held_seats,
                }
            ],
        )
    updated = CapacitySnapshot(
        capacity=new_capacity,
        confirmed_seats=snapshot.confirmed_seats,
        held_seats=snapshot.held_seats,
        waitlisted_count=snapshot.waitlisted_count,
        waitlist_capacity=(
            int(payload["waitlist_capacity"])
            if payload.get("waitlist_capacity") is not None
            else snapshot.waitlist_capacity
        ),
        sales_state=snapshot.sales_state,
    )
    ensure_not_oversold(updated)
    await _write_counter(
        session,
        ticket_type_id=ticket_type_id,
        snapshot=updated,
        expected_version=int(row["version"]),
    )
    await _record_event(
        session,
        activity_id=UUID(str(row["activity_id"])),
        ticket_type_id=ticket_type_id,
        registration_id=None,
        event_type="capacity_adjusted",
        seats=new_capacity,
        actor_id=actor_id,
        reason=str(payload["reason"]),
        metadata={"previous_capacity": snapshot.capacity},
    )
    # Raising the cap frees seats, so promote immediately rather than leaving a
    # queue waiting for the next cancellation.
    promotions = await _run_promotion_round_locked(
        session,
        ticket_type_id=ticket_type_id,
        activity_id=UUID(str(row["activity_id"])),
        counter_row={**row, "version": int(row["version"]) + 1},
        snapshot=updated,
        allow_skip_oversized=bool(get_settings().waitlist_allow_skip_oversized),
        max_offers=int(get_settings().waitlist_promotion_batch_size),
        dry_run=False,
    )
    return {"ticket_type_id": str(ticket_type_id), "capacity": new_capacity, **promotions}


async def set_sales_state(
    session: AsyncSession, *, ticket_type_id: UUID, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    capacity_guard_enabled()
    row = await _lock_counter(session, ticket_type_id)
    snapshot = _snapshot(row)
    updated = CapacitySnapshot(
        capacity=snapshot.capacity,
        confirmed_seats=snapshot.confirmed_seats,
        held_seats=snapshot.held_seats,
        waitlisted_count=snapshot.waitlisted_count,
        waitlist_capacity=snapshot.waitlist_capacity,
        sales_state=SalesState(str(payload["sales_state"])),
    )
    await _write_counter(
        session,
        ticket_type_id=ticket_type_id,
        snapshot=updated,
        expected_version=int(row["version"]),
    )
    await _record_event(
        session,
        activity_id=UUID(str(row["activity_id"])),
        ticket_type_id=ticket_type_id,
        registration_id=None,
        event_type="sales_state_changed",
        seats=0,
        actor_id=actor_id,
        reason=str(payload["reason"]),
        metadata={"from": snapshot.sales_state.value, "to": updated.sales_state.value},
    )
    return {"ticket_type_id": str(ticket_type_id), "sales_state": updated.sales_state.value}


async def list_waitlist(session: AsyncSession, *, ticket_type_id: UUID) -> list[dict[str, Any]]:
    entries, index = await _load_waitlist(session, ticket_type_id)
    return [
        {
            "position": position,
            "waitlist_entry_id": str(index[entry.registration_id]),
            "registration_id": str(entry.registration_id),
            "seats": entry.seats,
            "priority": entry.priority,
            "status": entry.status,
            "joined_at": entry.joined_at.isoformat(),
        }
        for position, entry in enumerate(ordered_waitlist(entries), start=1)
    ]
