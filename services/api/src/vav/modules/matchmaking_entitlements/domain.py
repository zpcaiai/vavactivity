"""Pure matchmaking eligibility and entitlement rules (B12).

Requirement coverage:

* MATCH-001 relationship status is an authorization prerequisite, not a filter
* MATCH-002 three free attempts, at most three candidates, success-only deduction
* MATCH-003 wait pool, history de-duplication, one notification per opportunity

No database, settings or clock access: every function takes what it needs so the
rules can be unit-tested on a machine with no PostgreSQL.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID


class MatchmakingRuleError(Exception):
    def __init__(self, code: str, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


# ---------------------------------------------------------------------------
# MATCH-001 relationship status gate
# ---------------------------------------------------------------------------


class RelationshipStatus(StrEnum):
    """Declared relationship status.

    ``UNDISCLOSED`` is the state of a member who has never answered. It is
    deliberately *not* treated as single: matchmaking stays closed until the
    member states they are single, so the default fails closed.
    """

    UNDISCLOSED = "undisclosed"
    SINGLE = "single"
    DATING = "dating"
    ENGAGED = "engaged"
    MARRIED = "married"
    SEPARATED = "separated"
    WIDOWED = "widowed"


#: The only statuses that may reach matchmaking at all.
MATCHMAKING_ELIGIBLE_STATUSES: frozenset[RelationshipStatus] = frozenset(
    {RelationshipStatus.SINGLE, RelationshipStatus.SEPARATED, RelationshipStatus.WIDOWED}
)


class StatusSource(StrEnum):
    SELF_DECLARED = "self_declared"
    #: Set automatically when a two-sided couple binding is confirmed (B16).
    COUPLE_BINDING = "couple_binding"
    ADMIN = "admin"


def is_matchmaking_allowed(status: str | None) -> bool:
    """Single source of truth for MATCH-001.

    Called from route guards, API handlers, background jobs and entitlement
    displays alike, so "hidden for non-single members" cannot drift between
    layers.
    """

    if status is None:
        return False
    try:
        return RelationshipStatus(status) in MATCHMAKING_ELIGIBLE_STATUSES
    except ValueError:
        return False


def ensure_matchmaking_allowed(status: str | None) -> None:
    if not is_matchmaking_allowed(status):
        raise MatchmakingRuleError(
            "MATCHMAKING_NOT_AVAILABLE",
            "Matchmaking is only available to members who have declared they are single.",
            details={"relationship_status": status or RelationshipStatus.UNDISCLOSED.value},
        )


def validate_status_change(
    *, current: str | None, target: str, source: str, locked_by_couple_binding: bool
) -> RelationshipStatus:
    """Guard a relationship-status write.

    A status set by a confirmed couple binding cannot be self-declared away:
    the member must unbind first. Otherwise one partner could unilaterally
    reopen matchmaking while the relationship record still says otherwise.
    """

    try:
        target_status = RelationshipStatus(target)
        status_source = StatusSource(source)
    except ValueError as exc:
        raise MatchmakingRuleError("RELATIONSHIP_STATUS_UNKNOWN", str(exc)) from exc
    if locked_by_couple_binding and status_source is StatusSource.SELF_DECLARED:
        raise MatchmakingRuleError(
            "RELATIONSHIP_STATUS_LOCKED",
            "This status is maintained by a confirmed partner binding. "
            "Unbind first to change it.",
        )
    if current is not None and current == target_status:
        raise MatchmakingRuleError(
            "RELATIONSHIP_STATUS_UNCHANGED", "The relationship status is already set to that value."
        )
    return target_status


# ---------------------------------------------------------------------------
# MATCH-002 free attempt ledger
# ---------------------------------------------------------------------------

#: V1.6: three free attempts, each returning at most three candidates.
DEFAULT_FREE_ATTEMPTS = 3
MAX_CANDIDATES_PER_ATTEMPT = 3


class LedgerReason(StrEnum):
    GRANT = "grant"
    CONSUME = "consume"
    REFUND = "refund"
    EXPIRE = "expire"
    ADMIN_ADJUST = "admin_adjust"


@dataclass(frozen=True)
class EntitlementState:
    granted: int
    consumed: int
    expires_at: datetime | None = None
    #: DEC-004 is unresolved. ``policy_version`` records which grant policy a
    #: balance was created under, so a later decision can be applied to new
    #: grants without rewriting history.
    policy_version: str = "dec-004-pending"

    @property
    def balance(self) -> int:
        return max(0, self.granted - self.consumed)

    def is_expired(self, now: datetime) -> bool:
        if self.expires_at is None:
            return False
        if now.tzinfo is None or self.expires_at.tzinfo is None:
            raise MatchmakingRuleError(
                "ENTITLEMENT_NAIVE_DATETIME", "Entitlement timestamps must be timezone-aware."
            )
        return now >= self.expires_at


@dataclass(frozen=True)
class ConsumptionDecision:
    """Outcome of one generation attempt."""

    should_consume: bool
    delivered: tuple[UUID, ...]
    reason_code: str
    enter_wait_pool: bool


def decide_consumption(
    state: EntitlementState,
    *,
    fresh_candidates: Sequence[UUID],
    now: datetime,
    max_candidates: int = MAX_CANDIDATES_PER_ATTEMPT,
) -> ConsumptionDecision:
    """Decide whether an attempt is spent.

    The rule that matters for MATCH-002: an attempt is deducted **only** when
    new eligible candidates are actually delivered. An empty or fully-repeated
    result costs nothing and instead puts the member in the wait pool.

    Balance and expiry are checked before candidates are looked at, so an
    exhausted member never learns whether anyone new exists.
    """

    if state.is_expired(now):
        raise MatchmakingRuleError(
            "ENTITLEMENT_EXPIRED",
            "The free matchmaking attempts for this account have expired.",
            details={"expires_at": state.expires_at.isoformat() if state.expires_at else None},
        )
    if state.balance <= 0:
        raise MatchmakingRuleError(
            "ENTITLEMENT_EXHAUSTED",
            "No free matchmaking attempts remain.",
            details={"granted": state.granted, "consumed": state.consumed},
        )
    if max_candidates > MAX_CANDIDATES_PER_ATTEMPT:
        raise MatchmakingRuleError(
            "ENTITLEMENT_LIMIT_INVALID",
            f"An attempt may return at most {MAX_CANDIDATES_PER_ATTEMPT} candidates.",
        )
    delivered = tuple(fresh_candidates[:max_candidates])
    if not delivered:
        return ConsumptionDecision(
            should_consume=False,
            delivered=(),
            reason_code="NO_NEW_CANDIDATES",
            enter_wait_pool=True,
        )
    return ConsumptionDecision(
        should_consume=True,
        delivered=delivered,
        reason_code="DELIVERED",
        enter_wait_pool=False,
    )


def apply_ledger_entry(state: EntitlementState, *, delta: int, reason: str) -> EntitlementState:
    """Return the state after one ledger line. Never produces a negative balance."""

    try:
        ledger_reason = LedgerReason(reason)
    except ValueError as exc:
        raise MatchmakingRuleError("LEDGER_REASON_UNKNOWN", str(exc)) from exc
    if ledger_reason is LedgerReason.CONSUME:
        if delta >= 0:
            raise MatchmakingRuleError("LEDGER_DELTA_INVALID", "A consumption must be negative.")
        if state.balance + delta < 0:
            raise MatchmakingRuleError(
                "ENTITLEMENT_OVERDRAWN",
                "This consumption would overdraw the entitlement balance.",
                details={"balance": state.balance, "delta": delta},
            )
        return EntitlementState(
            granted=state.granted,
            consumed=state.consumed - delta,
            expires_at=state.expires_at,
            policy_version=state.policy_version,
        )
    if ledger_reason is LedgerReason.REFUND:
        if delta <= 0:
            raise MatchmakingRuleError("LEDGER_DELTA_INVALID", "A refund must be positive.")
        if state.consumed - delta < 0:
            raise MatchmakingRuleError(
                "ENTITLEMENT_REFUND_EXCEEDS_USE",
                "A refund cannot return more attempts than were consumed.",
            )
        return EntitlementState(
            granted=state.granted,
            consumed=state.consumed - delta,
            expires_at=state.expires_at,
            policy_version=state.policy_version,
        )
    if ledger_reason is LedgerReason.EXPIRE:
        # Expiry burns the remaining balance without pretending it was used.
        return EntitlementState(
            granted=state.granted,
            consumed=state.granted,
            expires_at=state.expires_at,
            policy_version=state.policy_version,
        )
    if delta < 0 and state.granted + delta < state.consumed:
        raise MatchmakingRuleError(
            "ENTITLEMENT_GRANT_BELOW_USE",
            "A grant cannot be reduced below the number already consumed.",
        )
    return EntitlementState(
        granted=state.granted + delta,
        consumed=state.consumed,
        expires_at=state.expires_at,
        policy_version=state.policy_version,
    )


def consumption_idempotency_key(user_id: UUID, batch_id: UUID) -> str:
    """One ledger line per generated batch, however many times it is retried."""

    return f"matchmaking-consume:{user_id}:{batch_id}"


# ---------------------------------------------------------------------------
# MATCH-003 de-duplication and wait pool
# ---------------------------------------------------------------------------


def filter_new_candidates(
    candidates: Sequence[UUID],
    *,
    already_delivered: Iterable[UUID],
    excluded: Iterable[UUID] = (),
) -> list[UUID]:
    """Drop anyone this member has already been shown, plus hard exclusions.

    Input order is preserved, which keeps the ranking upstream meaningful.
    """

    seen = set(already_delivered) | set(excluded)
    result: list[UUID] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        result.append(candidate)
    return result


class WaitPoolStatus(StrEnum):
    WAITING = "waiting"
    NOTIFIED = "notified"
    EXITED = "exited"


_WAIT_POOL_TRANSITIONS: dict[WaitPoolStatus, frozenset[WaitPoolStatus]] = {
    WaitPoolStatus.WAITING: frozenset({WaitPoolStatus.NOTIFIED, WaitPoolStatus.EXITED}),
    # A notified member goes back to waiting only if they look and find nothing.
    WaitPoolStatus.NOTIFIED: frozenset({WaitPoolStatus.WAITING, WaitPoolStatus.EXITED}),
    WaitPoolStatus.EXITED: frozenset({WaitPoolStatus.WAITING}),
}


def validate_wait_pool_transition(current: str, target: str) -> None:
    try:
        current_status = WaitPoolStatus(current)
        target_status = WaitPoolStatus(target)
    except ValueError as exc:
        raise MatchmakingRuleError("WAIT_POOL_STATUS_UNKNOWN", str(exc)) from exc
    if target_status not in _WAIT_POOL_TRANSITIONS[current_status]:
        raise MatchmakingRuleError(
            "WAIT_POOL_TRANSITION_INVALID",
            f"Cannot move wait-pool entry from {current_status} to {target_status}.",
        )


def should_notify_arrival(
    *,
    status: str,
    last_notified_at: datetime | None,
    now: datetime,
    new_candidate_count: int,
    cooldown_hours: int = 24,
) -> bool:
    """One notification per opportunity, not one per job run.

    The cooldown makes the arrival job idempotent under retries and prevents a
    stream of new profiles from turning into a stream of pings.
    """

    if new_candidate_count <= 0:
        return False
    if status == WaitPoolStatus.EXITED:
        return False
    if last_notified_at is None:
        return True
    if now.tzinfo is None or last_notified_at.tzinfo is None:
        raise MatchmakingRuleError(
            "WAIT_POOL_NAIVE_DATETIME", "Wait-pool timestamps must be timezone-aware."
        )
    return now - last_notified_at >= timedelta(hours=cooldown_hours)


def arrival_notification_dedupe_key(user_id: UUID, opportunity_key: str) -> str:
    return f"matchmaking-arrival:{user_id}:{opportunity_key}"
