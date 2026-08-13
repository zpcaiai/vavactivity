"""Pure capacity and waitlist-promotion rules (B06 / ACT-003).

This module has no database, settings, network or clock access. Every function
that needs the current time takes ``now`` as an argument, and every function
that needs stored state takes it as a plain value, so the whole rule set is
unit-testable without PostgreSQL.

Requirement coverage:

* ACT-003 capacity must hold under concurrency. Concurrency itself is a service
  concern - the guard there takes a row lock on the ticket type before it reads
  counts (``SELECT ... FOR UPDATE``), never a read-then-write. What lives here
  is the arithmetic that lock protects, expressed as an explicit *transition*
  (:func:`apply_seat_grant`) rather than as a bare "is there room" predicate,
  so that a caller reusing a stale snapshot produces a loud
  ``CAPACITY_OVERSOLD`` instead of a quietly oversold event.
* ACT-003 deterministic waitlist promotion order. Ties are broken all the way
  down to the registration id, so two replicas planning promotions from the same
  state choose the same people in the same order.
* ACT-003 promotion offers are notified and expire. An offer holds a seat, so
  an offer without a TTL is a seat lost to somebody who stopped reading their
  notifications.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

# ---------------------------------------------------------------------------
# Shared errors
# ---------------------------------------------------------------------------


class CapacityRuleError(Exception):
    """Raised when a caller violates a capacity or waitlist rule.

    ``code`` is the stable machine identifier surfaced to clients; ``message``
    is an operator-facing English sentence. Member-facing copy is localized in
    the frontend from ``code``, never from ``message``.
    """

    def __init__(self, code: str, message: str, *, details: Mapping[str, object] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, object] = dict(details or {})


def _require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None:
        raise CapacityRuleError(
            "CAPACITY_NAIVE_DATETIME",
            f"{field_name} must be timezone-aware.",
            details={"field": field_name},
        )
    return value


# ---------------------------------------------------------------------------
# ACT-003 - the counted state
# ---------------------------------------------------------------------------


class SalesState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    SUSPENDED = "suspended"


@dataclass(frozen=True)
class CapacitySnapshot:
    """Seat accounting for one ticket type, as read under a row lock.

    Three buckets, deliberately separate:

    * ``confirmed_seats`` - people who are coming.
    * ``held_seats`` - seats reserved by an in-flight registration (pending
      payment, pending approval) or by a live promotion offer. Held seats are
      *not* available. Counting only confirmed seats is the classic oversell:
      fifty people each hold a seat through a payment page and all fifty
      succeed.
    * ``waitlisted_count`` - not seats at all; a waitlisted registration holds
      nothing.
    """

    capacity: int
    #: Catalog-derived mode. Zero is a valid finite cap, so the number cannot
    #: carry this meaning without making "sold out" indistinguishable from
    #: "uncapped".
    is_unlimited: bool = False
    confirmed_seats: int = 0
    held_seats: int = 0
    waitlisted_count: int = 0
    waitlist_capacity: int | None = None
    sales_state: SalesState = SalesState.OPEN

    def __post_init__(self) -> None:
        if self.capacity < 0:
            raise CapacityRuleError(
                "CAPACITY_INVALID",
                "Capacity cannot be negative.",
                details={"capacity": self.capacity},
            )
        if self.is_unlimited and self.capacity != 0:
            raise CapacityRuleError(
                "CAPACITY_UNLIMITED_VALUE_INVALID",
                "Unlimited capacity must store zero as its numeric placeholder.",
                details={"capacity": self.capacity},
            )
        for name in ("confirmed_seats", "held_seats", "waitlisted_count"):
            if getattr(self, name) < 0:
                raise CapacityRuleError(
                    "CAPACITY_COUNT_INVALID",
                    f"{name} cannot be negative.",
                    details={"field": name, "value": getattr(self, name)},
                )
        if self.waitlist_capacity is not None and self.waitlist_capacity < 0:
            raise CapacityRuleError(
                "CAPACITY_WAITLIST_INVALID",
                "Waitlist capacity cannot be negative.",
                details={"waitlist_capacity": self.waitlist_capacity},
            )

    @property
    def taken_seats(self) -> int:
        return self.confirmed_seats + self.held_seats


def is_unlimited(snapshot: CapacitySnapshot) -> bool:
    return snapshot.is_unlimited


def remaining_seats(snapshot: CapacitySnapshot) -> int:
    """Seats a new registration could actually take, never below zero."""

    if is_unlimited(snapshot):
        # Callers must branch on is_unlimited(); returning a sentinel integer
        # here would make "remaining" comparable to a real seat count and
        # produce silently wrong arithmetic.
        raise CapacityRuleError(
            "CAPACITY_UNLIMITED",
            "This ticket type has no seat cap; remaining seats is undefined.",
        )
    return max(0, snapshot.capacity - snapshot.taken_seats)


def ensure_not_oversold(snapshot: CapacitySnapshot) -> None:
    """Assert the invariant the whole module exists to protect.

    Called on the way in *and* on the way out of a transition. If it ever fires
    on the way in, the database is already inconsistent and the correct
    response is to refuse the write and page somebody, not to sell the seat.
    """

    if is_unlimited(snapshot):
        return
    if snapshot.taken_seats > snapshot.capacity:
        raise CapacityRuleError(
            "CAPACITY_OVERSOLD",
            "Seat counts exceed capacity.",
            details={
                "capacity": snapshot.capacity,
                "confirmed_seats": snapshot.confirmed_seats,
                "held_seats": snapshot.held_seats,
            },
        )


# ---------------------------------------------------------------------------
# ACT-003 - does this registration fit
# ---------------------------------------------------------------------------


class FitOutcome(StrEnum):
    FITS = "fits"
    WAITLIST = "waitlist"
    REJECTED = "rejected"


@dataclass(frozen=True)
class FitDecision:
    outcome: FitOutcome
    seats: int
    remaining_after: int | None
    reason_code: str | None


MAX_SEATS_PER_REGISTRATION = 20


def evaluate_fit(
    snapshot: CapacitySnapshot,
    *,
    requested_seats: int = 1,
    waitlist_enabled: bool = True,
) -> FitDecision:
    """Decide whether a registration takes a seat, joins the waitlist, or is refused.

    This is a *read* decision. It is only trustworthy when the caller holds the
    row lock; the moment it is computed outside one, it is a guess about the
    past. :func:`apply_seat_grant` is what makes acting on it safe.
    """

    if requested_seats < 1 or requested_seats > MAX_SEATS_PER_REGISTRATION:
        raise CapacityRuleError(
            "CAPACITY_SEATS_INVALID",
            f"Requested seats must be between 1 and {MAX_SEATS_PER_REGISTRATION}.",
            details={"requested_seats": requested_seats},
        )
    ensure_not_oversold(snapshot)

    if snapshot.sales_state is not SalesState.OPEN:
        return FitDecision(FitOutcome.REJECTED, requested_seats, None, "CAPACITY_SALES_CLOSED")
    if is_unlimited(snapshot):
        return FitDecision(FitOutcome.FITS, requested_seats, None, None)

    available = remaining_seats(snapshot)
    if requested_seats <= available:
        return FitDecision(FitOutcome.FITS, requested_seats, available - requested_seats, None)
    if not waitlist_enabled:
        return FitDecision(FitOutcome.REJECTED, requested_seats, available, "CAPACITY_FULL")
    if (
        snapshot.waitlist_capacity is not None
        and snapshot.waitlisted_count >= snapshot.waitlist_capacity
    ):
        return FitDecision(
            FitOutcome.REJECTED, requested_seats, available, "CAPACITY_WAITLIST_FULL"
        )
    return FitDecision(FitOutcome.WAITLIST, requested_seats, available, None)


def apply_seat_grant(
    snapshot: CapacitySnapshot, *, seats: int, hold: bool = True
) -> CapacitySnapshot:
    """Return the snapshot after granting ``seats``, or raise.

    Expressing the grant as a transition is the point. A caller that computed
    :func:`evaluate_fit` against a stale read and then applies the grant to the
    *current* snapshot gets ``CAPACITY_OVERSOLD`` here, which is exactly the
    lost-update the row lock is meant to prevent - and a test can demonstrate
    it without a database.
    """

    if seats < 1:
        raise CapacityRuleError(
            "CAPACITY_SEATS_INVALID", "Seats granted must be positive.", details={"seats": seats}
        )
    ensure_not_oversold(snapshot)
    if hold:
        updated = CapacitySnapshot(
            capacity=snapshot.capacity,
            is_unlimited=snapshot.is_unlimited,
            confirmed_seats=snapshot.confirmed_seats,
            held_seats=snapshot.held_seats + seats,
            waitlisted_count=snapshot.waitlisted_count,
            waitlist_capacity=snapshot.waitlist_capacity,
            sales_state=snapshot.sales_state,
        )
    else:
        updated = CapacitySnapshot(
            capacity=snapshot.capacity,
            is_unlimited=snapshot.is_unlimited,
            confirmed_seats=snapshot.confirmed_seats + seats,
            held_seats=snapshot.held_seats,
            waitlisted_count=snapshot.waitlisted_count,
            waitlist_capacity=snapshot.waitlist_capacity,
            sales_state=snapshot.sales_state,
        )
    ensure_not_oversold(updated)
    return updated


def apply_seat_release(
    snapshot: CapacitySnapshot, *, seats: int, from_hold: bool
) -> CapacitySnapshot:
    """Return the snapshot after a cancellation, expiry or hold release."""

    if seats < 1:
        raise CapacityRuleError(
            "CAPACITY_SEATS_INVALID", "Seats released must be positive.", details={"seats": seats}
        )
    bucket = snapshot.held_seats if from_hold else snapshot.confirmed_seats
    if seats > bucket:
        raise CapacityRuleError(
            "CAPACITY_RELEASE_UNDERFLOW",
            "Cannot release more seats than are held.",
            details={"seats": seats, "bucket": bucket, "from_hold": from_hold},
        )
    return CapacitySnapshot(
        capacity=snapshot.capacity,
        is_unlimited=snapshot.is_unlimited,
        confirmed_seats=snapshot.confirmed_seats - (0 if from_hold else seats),
        held_seats=snapshot.held_seats - (seats if from_hold else 0),
        waitlisted_count=snapshot.waitlisted_count,
        waitlist_capacity=snapshot.waitlist_capacity,
        sales_state=snapshot.sales_state,
    )


def confirm_held_seats(snapshot: CapacitySnapshot, *, seats: int) -> CapacitySnapshot:
    """Move seats from held to confirmed once payment or approval lands."""

    if seats < 1 or seats > snapshot.held_seats:
        raise CapacityRuleError(
            "CAPACITY_CONFIRM_INVALID",
            "Cannot confirm more seats than are currently held.",
            details={"seats": seats, "held_seats": snapshot.held_seats},
        )
    updated = CapacitySnapshot(
        capacity=snapshot.capacity,
        is_unlimited=snapshot.is_unlimited,
        confirmed_seats=snapshot.confirmed_seats + seats,
        held_seats=snapshot.held_seats - seats,
        waitlisted_count=snapshot.waitlisted_count,
        waitlist_capacity=snapshot.waitlist_capacity,
        sales_state=snapshot.sales_state,
    )
    ensure_not_oversold(updated)
    return updated


# ---------------------------------------------------------------------------
# ACT-003 - the waitlist
# ---------------------------------------------------------------------------


class WaitlistStatus(StrEnum):
    WAITING = "waiting"
    OFFERED = "offered"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"


#: Statuses that still occupy a place in the queue.
ACTIVE_WAITLIST_STATUSES: frozenset[str] = frozenset(
    {WaitlistStatus.WAITING, WaitlistStatus.OFFERED}
)

_WAITLIST_TRANSITIONS: dict[WaitlistStatus, frozenset[WaitlistStatus]] = {
    WaitlistStatus.WAITING: frozenset({WaitlistStatus.OFFERED, WaitlistStatus.WITHDRAWN}),
    # An expired offer returns the member to WAITING rather than dropping them:
    # missing one notification should not cost a place in the queue, but it does
    # cost this round's seat (see promote_after_expiry).
    WaitlistStatus.OFFERED: frozenset(
        {
            WaitlistStatus.ACCEPTED,
            WaitlistStatus.DECLINED,
            WaitlistStatus.EXPIRED,
            WaitlistStatus.WITHDRAWN,
        }
    ),
    WaitlistStatus.EXPIRED: frozenset({WaitlistStatus.WAITING, WaitlistStatus.WITHDRAWN}),
    WaitlistStatus.DECLINED: frozenset({WaitlistStatus.WITHDRAWN}),
    WaitlistStatus.ACCEPTED: frozenset(),
    WaitlistStatus.WITHDRAWN: frozenset(),
}


def validate_waitlist_transition(current: str, target: str) -> None:
    """Guard the waitlist lifecycle."""

    try:
        current_status = WaitlistStatus(current)
        target_status = WaitlistStatus(target)
    except ValueError as exc:  # pragma: no cover - defensive
        raise CapacityRuleError(
            "WAITLIST_STATUS_UNKNOWN", f"Unknown waitlist status: {exc}"
        ) from exc
    if target_status not in _WAITLIST_TRANSITIONS[current_status]:
        raise CapacityRuleError(
            "WAITLIST_TRANSITION_INVALID",
            f"Cannot move a waitlist entry from {current_status} to {target_status}.",
            details={"current": current_status.value, "target": target_status.value},
        )


@dataclass(frozen=True)
class WaitlistEntry:
    """One member's place in the queue for one ticket type."""

    registration_id: UUID
    user_id: UUID
    joined_at: datetime
    seats: int = 1
    #: Higher wins. Reserved for documented policies (a member bumped by an
    #: operator error, an accessibility accommodation). Default zero means the
    #: queue is plain first-come-first-served, which is what members expect.
    priority: int = 0
    status: str = WaitlistStatus.WAITING

    def __post_init__(self) -> None:
        _require_aware(self.joined_at, "joined_at")
        if self.seats < 1:
            raise CapacityRuleError(
                "WAITLIST_SEATS_INVALID",
                "A waitlist entry must ask for at least one seat.",
                details={"seats": self.seats},
            )


def waitlist_sort_key(entry: WaitlistEntry) -> tuple[int, float, str]:
    """Deterministic promotion order: priority desc, joined_at asc, id asc.

    The registration id is the final tie-break rather than a database ordering
    accident, so the same queue produces the same order on every replica and in
    every replay. Without it, two rows sharing a timestamp - which happens when
    a batch import creates a queue - could promote in either order, and "why did
    they get in before me" would have no answer.
    """

    return (-entry.priority, entry.joined_at.timestamp(), str(entry.registration_id))


def ordered_waitlist(entries: Iterable[WaitlistEntry]) -> list[WaitlistEntry]:
    """The queue, in promotion order, active entries only."""

    return sorted(
        (entry for entry in entries if entry.status in ACTIVE_WAITLIST_STATUSES),
        key=waitlist_sort_key,
    )


def waitlist_position(entries: Iterable[WaitlistEntry], registration_id: UUID) -> int:
    """1-based position, or raise if the entry is not queued."""

    for index, entry in enumerate(ordered_waitlist(entries), start=1):
        if entry.registration_id == registration_id:
            return index
    raise CapacityRuleError(
        "WAITLIST_ENTRY_NOT_FOUND",
        "That registration is not on the waitlist.",
        details={"registration_id": str(registration_id)},
    )


def select_next_promotions(
    entries: Sequence[WaitlistEntry],
    *,
    seats_available: int,
    allow_skip_oversized: bool = False,
    max_offers: int = 50,
) -> list[WaitlistEntry]:
    """Choose who is offered the seats that just freed up.

    Entries already holding a live offer are skipped: their seat is in
    ``held_seats`` and re-offering it would sell it twice.

    ``allow_skip_oversized`` is the honest name for a real trade-off. With it
    off (the default) a party of three at the head of a queue with two seats
    *blocks* - the queue stays fair and the seats wait for a bigger release.
    With it on, smaller parties behind them are promoted first, which fills the
    room but silently reorders the queue. Because that is a policy choice with
    a member-visible consequence, it is a parameter here rather than a hidden
    optimisation.
    """

    if seats_available < 0:
        raise CapacityRuleError(
            "CAPACITY_SEATS_INVALID",
            "Seats available cannot be negative.",
            details={"seats_available": seats_available},
        )
    promoted: list[WaitlistEntry] = []
    budget = seats_available
    for entry in ordered_waitlist(entries):
        if budget <= 0 or len(promoted) >= max_offers:
            break
        if entry.status == WaitlistStatus.OFFERED:
            continue
        if entry.seats > budget:
            if allow_skip_oversized:
                continue
            break
        promoted.append(entry)
        budget -= entry.seats
    return promoted


# ---------------------------------------------------------------------------
# ACT-003 - promotion offers
# ---------------------------------------------------------------------------


class OfferState(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class PromotionOffer:
    """A held seat with a deadline attached."""

    offer_id: UUID
    registration_id: UUID
    seats: int
    offered_at: datetime
    expires_at: datetime
    state: str = OfferState.PENDING
    notified_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_aware(self.offered_at, "offered_at")
        _require_aware(self.expires_at, "expires_at")
        if self.expires_at <= self.offered_at:
            raise CapacityRuleError(
                "PROMOTION_OFFER_TTL_INVALID",
                "A promotion offer must expire after it is made.",
                details={
                    "offered_at": self.offered_at.isoformat(),
                    "expires_at": self.expires_at.isoformat(),
                },
            )


MIN_OFFER_TTL_MINUTES = 15
MAX_OFFER_TTL_MINUTES = 10080


def offer_deadline(offered_at: datetime, *, ttl_minutes: int) -> datetime:
    """Compute an offer's expiry, refusing TTLs nobody could act on.

    A five-minute TTL on a notification that arrives by email is not an offer,
    it is a formality before the seat goes to someone else; the floor exists so
    a misconfiguration cannot quietly produce that.
    """

    _require_aware(offered_at, "offered_at")
    if ttl_minutes < MIN_OFFER_TTL_MINUTES or ttl_minutes > MAX_OFFER_TTL_MINUTES:
        raise CapacityRuleError(
            "PROMOTION_OFFER_TTL_INVALID",
            (
                f"Offer TTL must be between {MIN_OFFER_TTL_MINUTES} and "
                f"{MAX_OFFER_TTL_MINUTES} minutes."
            ),
            details={"ttl_minutes": ttl_minutes},
        )
    return offered_at + timedelta(minutes=ttl_minutes)


def clamp_offer_deadline(
    offered_at: datetime, *, ttl_minutes: int, event_starts_at: datetime | None
) -> datetime:
    """Never let an offer outlive the event it is an offer to attend.

    An offer that expires after the doors open is worthless to the member and
    holds a seat nobody can use, so the event start is a hard ceiling. If the
    event has already started the offer is refused outright rather than issued
    with a deadline in the past.
    """

    deadline = offer_deadline(offered_at, ttl_minutes=ttl_minutes)
    if event_starts_at is None:
        return deadline
    _require_aware(event_starts_at, "event_starts_at")
    if event_starts_at <= offered_at:
        raise CapacityRuleError(
            "PROMOTION_OFFER_TOO_LATE",
            "The event has already started; no promotion offer can be made.",
            details={"event_starts_at": event_starts_at.isoformat()},
        )
    return min(deadline, event_starts_at)


def is_promotion_offer_expired(offer: PromotionOffer, *, now: datetime) -> bool:
    """Pure expiry check, exclusive of the deadline instant.

    Expiry is a property of the clock, not of a background job having run: an
    offer whose sweeper is late is still expired, and every read path asks this
    question rather than trusting ``state``.
    """

    _require_aware(now, "now")
    if offer.state != OfferState.PENDING:
        return offer.state == OfferState.EXPIRED
    return now >= offer.expires_at


def offer_seconds_remaining(offer: PromotionOffer, *, now: datetime) -> int:
    """Countdown for the member-facing screen; zero once expired."""

    _require_aware(now, "now")
    if is_promotion_offer_expired(offer, now=now):
        return 0
    return max(0, int((offer.expires_at - now).total_seconds()))


class OfferResponse(StrEnum):
    ACCEPT = "accept"
    DECLINE = "decline"


@dataclass(frozen=True)
class OfferResolution:
    state: OfferState
    seats_confirmed: int
    seats_released: int
    waitlist_status: WaitlistStatus


def resolve_offer_response(
    offer: PromotionOffer, *, response: OfferResponse, now: datetime
) -> OfferResolution:
    """Apply a member's answer to a promotion offer.

    Expiry is checked *before* the response, so a member who taps accept as the
    timer hits zero is refused rather than racing the sweeper. That is the
    conservative direction: the alternative admits somebody into a seat that may
    already have been offered onward.
    """

    _require_aware(now, "now")
    if offer.state != OfferState.PENDING:
        raise CapacityRuleError(
            "PROMOTION_OFFER_NOT_PENDING",
            f"This promotion offer is already {offer.state}.",
            details={"state": str(offer.state)},
        )
    if is_promotion_offer_expired(offer, now=now):
        raise CapacityRuleError(
            "PROMOTION_OFFER_EXPIRED",
            "This promotion offer has expired.",
            details={"expires_at": offer.expires_at.isoformat()},
        )
    if response is OfferResponse.ACCEPT:
        return OfferResolution(OfferState.ACCEPTED, offer.seats, 0, WaitlistStatus.ACCEPTED)
    return OfferResolution(OfferState.DECLINED, 0, offer.seats, WaitlistStatus.DECLINED)


def expire_offer(offer: PromotionOffer, *, now: datetime) -> OfferResolution:
    """Sweep one expired offer, releasing its held seats back to the pool."""

    if not is_promotion_offer_expired(offer, now=now):
        raise CapacityRuleError(
            "PROMOTION_OFFER_NOT_EXPIRED",
            "This promotion offer has not expired yet.",
            details={"expires_at": offer.expires_at.isoformat()},
        )
    if offer.state != OfferState.PENDING:
        raise CapacityRuleError(
            "PROMOTION_OFFER_NOT_PENDING",
            f"This promotion offer is already {offer.state}.",
            details={"state": str(offer.state)},
        )
    # Back to WAITING, not dropped: see _WAITLIST_TRANSITIONS.
    return OfferResolution(OfferState.EXPIRED, 0, offer.seats, WaitlistStatus.WAITING)


def promotion_dedupe_key(*, registration_id: UUID, round_number: int) -> str:
    """At-most-once key for the notification attached to one offer round.

    Keyed on the round rather than on the offer id so a retried planner that
    re-mints an offer id cannot notify the same member twice for the same
    release.
    """

    if round_number < 1:
        raise CapacityRuleError(
            "PROMOTION_ROUND_INVALID",
            "Promotion round numbers start at 1.",
            details={"round_number": round_number},
        )
    return f"waitlist-promotion:{registration_id}:{round_number}"


@dataclass(frozen=True)
class PromotionPlan:
    """What the service should do after seats were released."""

    promotions: tuple[WaitlistEntry, ...]
    seats_offered: int
    seats_left_unoffered: int
    blocked_by_party_size: bool


def plan_promotions_after_release(
    snapshot: CapacitySnapshot,
    entries: Sequence[WaitlistEntry],
    *,
    allow_skip_oversized: bool = False,
    max_offers: int = 50,
) -> PromotionPlan:
    """Plan a promotion round from the post-release snapshot.

    Returns a plan rather than performing it, so the service can write the
    offers, the held-seat increments and the notification outbox rows inside one
    transaction, and so a caller can show an operator what *would* happen.
    """

    ensure_not_oversold(snapshot)
    if is_unlimited(snapshot):
        # No cap means nobody should be queued in the first place; promote
        # everyone waiting rather than leaving a queue that can never drain.
        waiting = [
            entry for entry in ordered_waitlist(entries) if entry.status != WaitlistStatus.OFFERED
        ][:max_offers]
        return PromotionPlan(tuple(waiting), sum(e.seats for e in waiting), 0, False)

    available = remaining_seats(snapshot)
    promotions = select_next_promotions(
        entries,
        seats_available=available,
        allow_skip_oversized=allow_skip_oversized,
        max_offers=max_offers,
    )
    offered = sum(entry.seats for entry in promotions)
    queue = [entry for entry in ordered_waitlist(entries) if entry.status != WaitlistStatus.OFFERED]
    blocked = (
        not allow_skip_oversized
        and len(promotions) < len(queue)
        and available - offered > 0
        and any(entry.seats > available - offered for entry in queue[len(promotions) :])
    )
    return PromotionPlan(tuple(promotions), offered, available - offered, blocked)
