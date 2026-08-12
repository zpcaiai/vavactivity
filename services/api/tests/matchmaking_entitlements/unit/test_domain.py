"""Pure-domain tests for matchmaking eligibility and entitlements (B12)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from vav.modules.matchmaking_entitlements.domain import (
    DEFAULT_FREE_ATTEMPTS,
    MAX_CANDIDATES_PER_ATTEMPT,
    EntitlementState,
    MatchmakingRuleError,
    RelationshipStatus,
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

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def _uid(value: int) -> UUID:
    return UUID(int=value)


# ---------------------------------------------------------------------------
# MATCH-001
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["single", "separated", "widowed"])
def test_eligible_statuses_open_matchmaking(status: str) -> None:
    assert is_matchmaking_allowed(status)


@pytest.mark.parametrize("status", ["dating", "engaged", "married", "undisclosed"])
def test_non_single_statuses_close_matchmaking(status: str) -> None:
    assert not is_matchmaking_allowed(status)


def test_missing_or_unknown_status_fails_closed() -> None:
    assert not is_matchmaking_allowed(None)
    assert not is_matchmaking_allowed("")
    assert not is_matchmaking_allowed("its_complicated")


def test_ensure_raises_with_the_status_in_the_details() -> None:
    with pytest.raises(MatchmakingRuleError) as excinfo:
        ensure_matchmaking_allowed("married")
    assert excinfo.value.code == "MATCHMAKING_NOT_AVAILABLE"
    assert excinfo.value.details["relationship_status"] == "married"
    with pytest.raises(MatchmakingRuleError) as unset:
        ensure_matchmaking_allowed(None)
    assert unset.value.details["relationship_status"] == RelationshipStatus.UNDISCLOSED


def test_couple_bound_status_cannot_be_self_declared_away() -> None:
    with pytest.raises(MatchmakingRuleError) as excinfo:
        validate_status_change(
            current="dating",
            target="single",
            source="self_declared",
            locked_by_couple_binding=True,
        )
    assert excinfo.value.code == "RELATIONSHIP_STATUS_LOCKED"
    # The binding itself, and an administrator, may still change it.
    assert (
        validate_status_change(
            current="dating",
            target="single",
            source="couple_binding",
            locked_by_couple_binding=True,
        )
        is RelationshipStatus.SINGLE
    )
    assert (
        validate_status_change(
            current="dating", target="single", source="admin", locked_by_couple_binding=True
        )
        is RelationshipStatus.SINGLE
    )


def test_redundant_status_write_is_rejected() -> None:
    with pytest.raises(MatchmakingRuleError) as excinfo:
        validate_status_change(
            current="single",
            target="single",
            source="self_declared",
            locked_by_couple_binding=False,
        )
    assert excinfo.value.code == "RELATIONSHIP_STATUS_UNCHANGED"


# ---------------------------------------------------------------------------
# MATCH-002
# ---------------------------------------------------------------------------


def _state(granted: int = DEFAULT_FREE_ATTEMPTS, consumed: int = 0, **kwargs) -> EntitlementState:
    return EntitlementState(granted=granted, consumed=consumed, **kwargs)


def test_default_grant_is_three_and_balance_tracks_use() -> None:
    assert DEFAULT_FREE_ATTEMPTS == 3
    assert _state().balance == 3
    assert _state(consumed=2).balance == 1
    assert _state(consumed=5).balance == 0


def test_an_attempt_returns_at_most_three_candidates() -> None:
    decision = decide_consumption(
        _state(), fresh_candidates=[_uid(i) for i in range(1, 8)], now=NOW
    )
    assert len(decision.delivered) == MAX_CANDIDATES_PER_ATTEMPT == 3
    assert decision.should_consume


def test_empty_result_does_not_deduct_and_enters_the_wait_pool() -> None:
    decision = decide_consumption(_state(), fresh_candidates=[], now=NOW)
    assert decision.should_consume is False
    assert decision.enter_wait_pool is True
    assert decision.reason_code == "NO_NEW_CANDIDATES"


def test_exhausted_balance_is_refused_before_candidates_are_considered() -> None:
    with pytest.raises(MatchmakingRuleError) as excinfo:
        decide_consumption(_state(consumed=3), fresh_candidates=[_uid(1)], now=NOW)
    assert excinfo.value.code == "ENTITLEMENT_EXHAUSTED"


def test_expired_entitlement_is_refused() -> None:
    state = _state(expires_at=NOW - timedelta(seconds=1))
    with pytest.raises(MatchmakingRuleError) as excinfo:
        decide_consumption(state, fresh_candidates=[_uid(1)], now=NOW)
    assert excinfo.value.code == "ENTITLEMENT_EXPIRED"
    # Not yet expired is fine.
    assert decide_consumption(
        _state(expires_at=NOW + timedelta(days=1)), fresh_candidates=[_uid(1)], now=NOW
    ).should_consume


def test_naive_expiry_is_rejected_rather_than_assumed_utc() -> None:
    state = _state(expires_at=datetime(2026, 8, 1, 0, 0))
    with pytest.raises(MatchmakingRuleError) as excinfo:
        decide_consumption(state, fresh_candidates=[_uid(1)], now=NOW)
    assert excinfo.value.code == "ENTITLEMENT_NAIVE_DATETIME"


def test_caller_cannot_raise_the_per_attempt_ceiling() -> None:
    with pytest.raises(MatchmakingRuleError) as excinfo:
        decide_consumption(_state(), fresh_candidates=[_uid(1)], now=NOW, max_candidates=5)
    assert excinfo.value.code == "ENTITLEMENT_LIMIT_INVALID"


def test_consumption_cannot_overdraw_the_ledger() -> None:
    state = _state(consumed=2)
    after = apply_ledger_entry(state, delta=-1, reason="consume")
    assert after.balance == 0
    with pytest.raises(MatchmakingRuleError) as excinfo:
        apply_ledger_entry(after, delta=-1, reason="consume")
    assert excinfo.value.code == "ENTITLEMENT_OVERDRAWN"


def test_consumption_sign_is_enforced() -> None:
    with pytest.raises(MatchmakingRuleError) as excinfo:
        apply_ledger_entry(_state(), delta=1, reason="consume")
    assert excinfo.value.code == "LEDGER_DELTA_INVALID"


def test_refund_returns_an_attempt_but_never_more_than_was_used() -> None:
    state = _state(consumed=1)
    assert apply_ledger_entry(state, delta=1, reason="refund").balance == 3
    with pytest.raises(MatchmakingRuleError) as excinfo:
        apply_ledger_entry(state, delta=2, reason="refund")
    assert excinfo.value.code == "ENTITLEMENT_REFUND_EXCEEDS_USE"


def test_expiry_burns_the_remaining_balance_without_faking_use() -> None:
    state = _state(consumed=1)
    expired = apply_ledger_entry(state, delta=0, reason="expire")
    assert expired.balance == 0
    assert expired.granted == 3


def test_admin_cannot_reduce_a_grant_below_what_was_consumed() -> None:
    with pytest.raises(MatchmakingRuleError) as excinfo:
        apply_ledger_entry(_state(consumed=2), delta=-2, reason="admin_adjust")
    assert excinfo.value.code == "ENTITLEMENT_GRANT_BELOW_USE"


def test_admin_can_grant_extra_attempts() -> None:
    assert apply_ledger_entry(_state(consumed=3), delta=2, reason="admin_adjust").balance == 2


def test_consumption_key_is_per_batch_so_a_retry_cannot_double_spend() -> None:
    user, batch = _uid(1), _uid(2)
    assert consumption_idempotency_key(user, batch) == consumption_idempotency_key(user, batch)
    assert consumption_idempotency_key(user, batch) != consumption_idempotency_key(user, _uid(3))


# ---------------------------------------------------------------------------
# MATCH-003
# ---------------------------------------------------------------------------


def test_previously_delivered_candidates_are_never_repeated() -> None:
    candidates = [_uid(1), _uid(2), _uid(3), _uid(4)]
    assert filter_new_candidates(candidates, already_delivered=[_uid(2), _uid(4)]) == [
        _uid(1),
        _uid(3),
    ]


def test_exclusions_and_input_duplicates_are_both_removed_preserving_rank_order() -> None:
    candidates = [_uid(5), _uid(1), _uid(5), _uid(9)]
    assert filter_new_candidates(candidates, already_delivered=[], excluded=[_uid(9)]) == [
        _uid(5),
        _uid(1),
    ]


def test_a_fully_repeated_result_costs_no_attempt() -> None:
    fresh = filter_new_candidates([_uid(1), _uid(2)], already_delivered=[_uid(1), _uid(2)])
    decision = decide_consumption(_state(), fresh_candidates=fresh, now=NOW)
    assert fresh == []
    assert decision.should_consume is False
    assert decision.enter_wait_pool is True


def test_wait_pool_transitions() -> None:
    validate_wait_pool_transition("waiting", "notified")
    validate_wait_pool_transition("notified", "waiting")
    validate_wait_pool_transition("notified", "exited")
    validate_wait_pool_transition("exited", "waiting")
    with pytest.raises(MatchmakingRuleError) as excinfo:
        validate_wait_pool_transition("exited", "notified")
    assert excinfo.value.code == "WAIT_POOL_TRANSITION_INVALID"


def test_no_notification_without_new_candidates() -> None:
    assert not should_notify_arrival(
        status=WaitPoolStatus.WAITING, last_notified_at=None, now=NOW, new_candidate_count=0
    )


def test_first_arrival_notifies_and_the_cooldown_then_suppresses_reruns() -> None:
    assert should_notify_arrival(
        status=WaitPoolStatus.WAITING, last_notified_at=None, now=NOW, new_candidate_count=2
    )
    assert not should_notify_arrival(
        status=WaitPoolStatus.NOTIFIED,
        last_notified_at=NOW - timedelta(hours=1),
        now=NOW,
        new_candidate_count=2,
    )
    assert should_notify_arrival(
        status=WaitPoolStatus.NOTIFIED,
        last_notified_at=NOW - timedelta(hours=25),
        now=NOW,
        new_candidate_count=2,
    )


def test_an_exited_member_is_never_notified() -> None:
    assert not should_notify_arrival(
        status=WaitPoolStatus.EXITED, last_notified_at=None, now=NOW, new_candidate_count=5
    )


def test_arrival_dedupe_key_is_stable_per_opportunity() -> None:
    user = _uid(1)
    assert arrival_notification_dedupe_key(user, "pool-v7") == arrival_notification_dedupe_key(
        user, "pool-v7"
    )
    assert arrival_notification_dedupe_key(user, "pool-v7") != arrival_notification_dedupe_key(
        user, "pool-v8"
    )
