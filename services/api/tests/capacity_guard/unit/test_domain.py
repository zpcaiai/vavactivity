"""Pure-domain tests for capacity and waitlist promotion (ACT-003).

These tests deliberately touch no database, no settings and no network, so they
run on any machine including one without PostgreSQL or Redis.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from vav.modules.capacity_guard.domain import (
    MAX_SEATS_PER_REGISTRATION,
    MIN_OFFER_TTL_MINUTES,
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
    offer_deadline,
    offer_seconds_remaining,
    ordered_waitlist,
    plan_promotions_after_release,
    promotion_dedupe_key,
    remaining_seats,
    resolve_offer_response,
    select_next_promotions,
    validate_waitlist_transition,
    waitlist_position,
    waitlist_sort_key,
)

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
EVENT_START = datetime(2026, 8, 14, 19, 0, tzinfo=UTC)


def _uid(value: int) -> UUID:
    return UUID(int=value)


def _entry(
    index: int,
    *,
    minutes: int = 0,
    seats: int = 1,
    priority: int = 0,
    status: str = WaitlistStatus.WAITING,
) -> WaitlistEntry:
    return WaitlistEntry(
        registration_id=_uid(index),
        user_id=_uid(1000 + index),
        joined_at=NOW + timedelta(minutes=minutes),
        seats=seats,
        priority=priority,
        status=status,
    )


def _offer(
    *, seats: int = 1, ttl_minutes: int = 60, state: str = OfferState.PENDING
) -> PromotionOffer:
    return PromotionOffer(
        offer_id=_uid(900),
        registration_id=_uid(1),
        seats=seats,
        offered_at=NOW,
        expires_at=NOW + timedelta(minutes=ttl_minutes),
        state=state,
    )


# ---------------------------------------------------------------------------
# The counted state
# ---------------------------------------------------------------------------


def test_held_seats_are_not_available_seats() -> None:
    """The classic oversell: fifty people on a payment page all succeed."""

    snapshot = CapacitySnapshot(capacity=50, confirmed_seats=10, held_seats=40)
    assert remaining_seats(snapshot) == 0
    assert snapshot.taken_seats == 50


def test_remaining_seats_never_goes_negative() -> None:
    snapshot = CapacitySnapshot(capacity=10, confirmed_seats=8, held_seats=1)
    assert remaining_seats(snapshot) == 1


def test_explicit_unlimited_mode_accepts_seats_without_a_ceiling() -> None:
    snapshot = CapacitySnapshot(capacity=0, is_unlimited=True, confirmed_seats=500)
    assert is_unlimited(snapshot)
    decision = evaluate_fit(snapshot, requested_seats=4)
    assert decision.outcome is FitOutcome.FITS


def test_finite_zero_capacity_is_sold_out_not_unlimited() -> None:
    snapshot = CapacitySnapshot(capacity=0, is_unlimited=False)

    assert not is_unlimited(snapshot)
    assert remaining_seats(snapshot) == 0
    decision = evaluate_fit(snapshot, requested_seats=1, waitlist_enabled=False)
    assert decision.outcome is FitOutcome.REJECTED
    assert decision.reason_code == "CAPACITY_FULL"


def test_remaining_seats_refuses_to_answer_for_an_uncapped_ticket_type() -> None:
    """A sentinel integer here would silently poison every comparison."""

    with pytest.raises(CapacityRuleError) as excinfo:
        remaining_seats(CapacitySnapshot(capacity=0, is_unlimited=True))
    assert excinfo.value.code == "CAPACITY_UNLIMITED"


def test_unlimited_mode_requires_zero_numeric_placeholder() -> None:
    with pytest.raises(CapacityRuleError) as excinfo:
        CapacitySnapshot(capacity=10, is_unlimited=True)
    assert excinfo.value.code == "CAPACITY_UNLIMITED_VALUE_INVALID"


def test_negative_counts_are_refused_at_construction() -> None:
    with pytest.raises(CapacityRuleError) as excinfo:
        CapacitySnapshot(capacity=10, confirmed_seats=-1)
    assert excinfo.value.code == "CAPACITY_COUNT_INVALID"
    with pytest.raises(CapacityRuleError):
        CapacitySnapshot(capacity=-5)


def test_an_already_oversold_row_is_refused_on_the_way_in() -> None:
    snapshot = CapacitySnapshot(capacity=10, confirmed_seats=9, held_seats=3)
    with pytest.raises(CapacityRuleError) as excinfo:
        ensure_not_oversold(snapshot)
    assert excinfo.value.code == "CAPACITY_OVERSOLD"


# ---------------------------------------------------------------------------
# Fit decisions
# ---------------------------------------------------------------------------


def test_a_request_that_fits_reports_what_is_left() -> None:
    decision = evaluate_fit(CapacitySnapshot(capacity=10, confirmed_seats=4), requested_seats=2)
    assert decision.outcome is FitOutcome.FITS
    assert decision.remaining_after == 4


def test_a_full_ticket_type_offers_the_waitlist() -> None:
    decision = evaluate_fit(CapacitySnapshot(capacity=2, confirmed_seats=2), requested_seats=1)
    assert decision.outcome is FitOutcome.WAITLIST


def test_a_member_who_declines_the_waitlist_is_simply_refused() -> None:
    decision = evaluate_fit(
        CapacitySnapshot(capacity=2, confirmed_seats=2), requested_seats=1, waitlist_enabled=False
    )
    assert decision.outcome is FitOutcome.REJECTED
    assert decision.reason_code == "CAPACITY_FULL"


def test_a_full_waitlist_is_its_own_refusal() -> None:
    snapshot = CapacitySnapshot(
        capacity=2, confirmed_seats=2, waitlisted_count=5, waitlist_capacity=5
    )
    decision = evaluate_fit(snapshot, requested_seats=1)
    assert decision.outcome is FitOutcome.REJECTED
    assert decision.reason_code == "CAPACITY_WAITLIST_FULL"


@pytest.mark.parametrize("state", [SalesState.CLOSED, SalesState.SUSPENDED])
def test_closed_sales_refuse_before_any_seat_arithmetic(state: SalesState) -> None:
    snapshot = CapacitySnapshot(capacity=100, sales_state=state)
    decision = evaluate_fit(snapshot, requested_seats=1)
    assert decision.outcome is FitOutcome.REJECTED
    assert decision.reason_code == "CAPACITY_SALES_CLOSED"


@pytest.mark.parametrize("seats", [0, -1, MAX_SEATS_PER_REGISTRATION + 1])
def test_an_absurd_party_size_is_refused(seats: int) -> None:
    with pytest.raises(CapacityRuleError) as excinfo:
        evaluate_fit(CapacitySnapshot(capacity=100), requested_seats=seats)
    assert excinfo.value.code == "CAPACITY_SEATS_INVALID"


# ---------------------------------------------------------------------------
# The concurrency invariant
# ---------------------------------------------------------------------------


def test_capacity_cannot_be_oversold_under_concurrent_fit_checks() -> None:
    """The requirement, stated as a test.

    Two requests read the *same* snapshot with one seat left - which is exactly
    what happens when the fit check runs outside a row lock - and both conclude
    they fit. Applying both grants must be impossible: the second raises
    ``CAPACITY_OVERSOLD`` rather than producing an eleventh seat in a room of
    ten. This is why the guard is a transition and not a predicate.
    """

    stale = CapacitySnapshot(capacity=10, confirmed_seats=9)
    first = evaluate_fit(stale, requested_seats=1)
    second = evaluate_fit(stale, requested_seats=1)
    assert first.outcome is FitOutcome.FITS
    assert second.outcome is FitOutcome.FITS  # both saw a free seat

    after_first = apply_seat_grant(stale, seats=1)
    assert after_first.taken_seats == 10

    with pytest.raises(CapacityRuleError) as excinfo:
        apply_seat_grant(after_first, seats=1)
    assert excinfo.value.code == "CAPACITY_OVERSOLD"


def test_the_serialized_path_sends_the_loser_to_the_waitlist() -> None:
    """What the row lock buys: the second caller re-reads and gets the truth."""

    snapshot = CapacitySnapshot(capacity=10, confirmed_seats=9)
    first = evaluate_fit(snapshot, requested_seats=1)
    assert first.outcome is FitOutcome.FITS
    snapshot = apply_seat_grant(snapshot, seats=1)
    second = evaluate_fit(snapshot, requested_seats=1)
    assert second.outcome is FitOutcome.WAITLIST


def test_a_burst_of_serialized_grants_stops_exactly_at_capacity() -> None:
    snapshot = CapacitySnapshot(capacity=5)
    granted = 0
    for _ in range(20):
        decision = evaluate_fit(snapshot, requested_seats=1)
        if decision.outcome is not FitOutcome.FITS:
            continue
        snapshot = apply_seat_grant(snapshot, seats=1)
        granted += 1
    assert granted == 5
    assert snapshot.taken_seats == 5
    ensure_not_oversold(snapshot)


def test_a_party_grant_cannot_straddle_the_cap() -> None:
    snapshot = CapacitySnapshot(capacity=10, confirmed_seats=8)
    with pytest.raises(CapacityRuleError):
        apply_seat_grant(snapshot, seats=3)


def test_holds_become_confirmations_without_changing_the_total() -> None:
    snapshot = CapacitySnapshot(capacity=10, confirmed_seats=2, held_seats=3)
    updated = confirm_held_seats(snapshot, seats=3)
    assert (updated.confirmed_seats, updated.held_seats) == (5, 0)
    assert updated.taken_seats == snapshot.taken_seats


def test_confirming_more_than_is_held_is_refused() -> None:
    with pytest.raises(CapacityRuleError) as excinfo:
        confirm_held_seats(CapacitySnapshot(capacity=10, held_seats=1), seats=2)
    assert excinfo.value.code == "CAPACITY_CONFIRM_INVALID"


def test_releasing_more_than_is_held_is_refused() -> None:
    with pytest.raises(CapacityRuleError) as excinfo:
        apply_seat_release(CapacitySnapshot(capacity=10, held_seats=1), seats=2, from_hold=True)
    assert excinfo.value.code == "CAPACITY_RELEASE_UNDERFLOW"


def test_a_release_frees_the_seat_it_says_it_frees() -> None:
    snapshot = CapacitySnapshot(capacity=10, confirmed_seats=4, held_seats=2)
    assert apply_seat_release(snapshot, seats=2, from_hold=True).held_seats == 0
    assert apply_seat_release(snapshot, seats=1, from_hold=False).confirmed_seats == 3


# ---------------------------------------------------------------------------
# Waitlist ordering
# ---------------------------------------------------------------------------


def test_the_queue_is_first_come_first_served_by_default() -> None:
    entries = [_entry(3, minutes=30), _entry(1, minutes=0), _entry(2, minutes=10)]
    assert [entry.registration_id for entry in ordered_waitlist(entries)] == [
        _uid(1),
        _uid(2),
        _uid(3),
    ]


def test_priority_beats_arrival_time() -> None:
    entries = [_entry(1, minutes=0), _entry(2, minutes=60, priority=5)]
    assert ordered_waitlist(entries)[0].registration_id == _uid(2)


def test_ties_are_broken_deterministically_by_registration_id() -> None:
    """Two rows sharing a timestamp - a batch import - must still have one order."""

    entries = [_entry(9, minutes=0), _entry(4, minutes=0), _entry(7, minutes=0)]
    first = [entry.registration_id for entry in ordered_waitlist(entries)]
    second = [entry.registration_id for entry in ordered_waitlist(list(reversed(entries)))]
    assert first == second == [_uid(4), _uid(7), _uid(9)]


def test_the_sort_key_is_priority_desc_then_time_then_id() -> None:
    key = waitlist_sort_key(_entry(1, minutes=5, priority=2))
    assert key[0] == -2
    assert key[2] == str(_uid(1))


def test_resolved_entries_leave_the_queue() -> None:
    entries = [
        _entry(1, status=WaitlistStatus.ACCEPTED),
        _entry(2, status=WaitlistStatus.WITHDRAWN),
        _entry(3, status=WaitlistStatus.WAITING),
    ]
    assert [entry.registration_id for entry in ordered_waitlist(entries)] == [_uid(3)]


def test_a_position_is_one_based_and_missing_entries_are_loud() -> None:
    entries = [_entry(1, minutes=0), _entry(2, minutes=1)]
    assert waitlist_position(entries, _uid(2)) == 2
    with pytest.raises(CapacityRuleError) as excinfo:
        waitlist_position(entries, _uid(99))
    assert excinfo.value.code == "WAITLIST_ENTRY_NOT_FOUND"


def test_a_waitlist_entry_must_ask_for_at_least_one_seat() -> None:
    with pytest.raises(CapacityRuleError) as excinfo:
        _entry(1, seats=0)
    assert excinfo.value.code == "WAITLIST_SEATS_INVALID"


def test_a_naive_join_timestamp_is_rejected() -> None:
    with pytest.raises(CapacityRuleError) as excinfo:
        WaitlistEntry(
            registration_id=_uid(1), user_id=_uid(2), joined_at=datetime(2026, 8, 12, 12, 0)
        )
    assert excinfo.value.code == "CAPACITY_NAIVE_DATETIME"


# ---------------------------------------------------------------------------
# Promotion selection
# ---------------------------------------------------------------------------


def test_promotions_take_the_head_of_the_queue_until_the_seats_run_out() -> None:
    entries = [_entry(index, minutes=index) for index in range(1, 6)]
    promoted = select_next_promotions(entries, seats_available=3)
    assert [entry.registration_id for entry in promoted] == [_uid(1), _uid(2), _uid(3)]


def test_an_entry_already_holding_an_offer_is_not_offered_twice() -> None:
    entries = [
        _entry(1, minutes=0, status=WaitlistStatus.OFFERED),
        _entry(2, minutes=1),
    ]
    promoted = select_next_promotions(entries, seats_available=1)
    assert [entry.registration_id for entry in promoted] == [_uid(2)]


def test_a_large_party_blocks_the_queue_by_default() -> None:
    """Fair, and deliberately visible: the seats wait for a bigger release."""

    entries = [_entry(1, minutes=0, seats=3), _entry(2, minutes=1, seats=1)]
    assert select_next_promotions(entries, seats_available=2) == []


def test_skipping_an_oversized_party_is_opt_in() -> None:
    entries = [_entry(1, minutes=0, seats=3), _entry(2, minutes=1, seats=1)]
    promoted = select_next_promotions(entries, seats_available=2, allow_skip_oversized=True)
    assert [entry.registration_id for entry in promoted] == [_uid(2)]


def test_no_seats_means_no_promotions() -> None:
    assert select_next_promotions([_entry(1)], seats_available=0) == []


def test_a_negative_seat_budget_is_a_programming_error() -> None:
    with pytest.raises(CapacityRuleError) as excinfo:
        select_next_promotions([_entry(1)], seats_available=-1)
    assert excinfo.value.code == "CAPACITY_SEATS_INVALID"


def test_max_offers_caps_one_round() -> None:
    entries = [_entry(index, minutes=index) for index in range(1, 11)]
    assert len(select_next_promotions(entries, seats_available=10, max_offers=3)) == 3


def test_a_plan_reports_what_it_could_not_offer() -> None:
    snapshot = CapacitySnapshot(capacity=10, confirmed_seats=8)
    entries = [_entry(1, minutes=0, seats=3), _entry(2, minutes=1, seats=1)]
    plan = plan_promotions_after_release(snapshot, entries)
    assert plan.promotions == ()
    assert plan.seats_left_unoffered == 2
    assert plan.blocked_by_party_size is True


def test_a_plan_promotes_when_the_head_of_the_queue_fits() -> None:
    snapshot = CapacitySnapshot(capacity=10, confirmed_seats=8)
    plan = plan_promotions_after_release(snapshot, [_entry(1, seats=2)])
    assert [entry.registration_id for entry in plan.promotions] == [_uid(1)]
    assert plan.seats_offered == 2
    assert plan.seats_left_unoffered == 0


def test_an_uncapped_ticket_type_drains_its_queue() -> None:
    """Nobody should be queued for an event with no cap in the first place."""

    plan = plan_promotions_after_release(
        CapacitySnapshot(capacity=0, is_unlimited=True), [_entry(1), _entry(2)]
    )
    assert len(plan.promotions) == 2


# ---------------------------------------------------------------------------
# Waitlist lifecycle
# ---------------------------------------------------------------------------


def test_an_expired_offer_returns_the_member_to_the_queue() -> None:
    validate_waitlist_transition(WaitlistStatus.OFFERED, WaitlistStatus.EXPIRED)
    validate_waitlist_transition(WaitlistStatus.EXPIRED, WaitlistStatus.WAITING)


def test_an_accepted_place_is_terminal() -> None:
    with pytest.raises(CapacityRuleError) as excinfo:
        validate_waitlist_transition(WaitlistStatus.ACCEPTED, WaitlistStatus.WAITING)
    assert excinfo.value.code == "WAITLIST_TRANSITION_INVALID"


def test_a_waiting_entry_cannot_jump_straight_to_accepted() -> None:
    with pytest.raises(CapacityRuleError):
        validate_waitlist_transition(WaitlistStatus.WAITING, WaitlistStatus.ACCEPTED)


def test_an_unknown_waitlist_status_is_rejected() -> None:
    with pytest.raises(CapacityRuleError) as excinfo:
        validate_waitlist_transition("waiting", "teleported")
    assert excinfo.value.code == "WAITLIST_STATUS_UNKNOWN"


# ---------------------------------------------------------------------------
# Promotion offers and their TTL
# ---------------------------------------------------------------------------


def test_an_offer_expires_on_the_clock_not_on_a_sweeper() -> None:
    offer = _offer(ttl_minutes=60)
    assert not is_promotion_offer_expired(offer, now=NOW + timedelta(minutes=59))
    assert is_promotion_offer_expired(offer, now=NOW + timedelta(minutes=60))


def test_a_countdown_reaches_zero_and_stays_there() -> None:
    offer = _offer(ttl_minutes=60)
    assert offer_seconds_remaining(offer, now=NOW + timedelta(minutes=30)) == 1800
    assert offer_seconds_remaining(offer, now=NOW + timedelta(minutes=90)) == 0


def test_an_unactionably_short_ttl_is_refused() -> None:
    with pytest.raises(CapacityRuleError) as excinfo:
        offer_deadline(NOW, ttl_minutes=MIN_OFFER_TTL_MINUTES - 1)
    assert excinfo.value.code == "PROMOTION_OFFER_TTL_INVALID"


def test_an_offer_never_outlives_the_event_it_is_an_offer_to_attend() -> None:
    deadline = clamp_offer_deadline(
        EVENT_START - timedelta(minutes=30), ttl_minutes=1440, event_starts_at=EVENT_START
    )
    assert deadline == EVENT_START


def test_no_offer_is_made_for_an_event_that_already_started() -> None:
    with pytest.raises(CapacityRuleError) as excinfo:
        clamp_offer_deadline(
            EVENT_START + timedelta(minutes=1), ttl_minutes=60, event_starts_at=EVENT_START
        )
    assert excinfo.value.code == "PROMOTION_OFFER_TOO_LATE"


def test_an_offer_that_expires_before_it_is_made_is_impossible() -> None:
    with pytest.raises(CapacityRuleError) as excinfo:
        PromotionOffer(
            offer_id=_uid(1),
            registration_id=_uid(2),
            seats=1,
            offered_at=NOW,
            expires_at=NOW - timedelta(minutes=1),
        )
    assert excinfo.value.code == "PROMOTION_OFFER_TTL_INVALID"


def test_accepting_an_offer_confirms_its_seats() -> None:
    resolution = resolve_offer_response(
        _offer(seats=2), response=OfferResponse.ACCEPT, now=NOW + timedelta(minutes=5)
    )
    assert resolution.state is OfferState.ACCEPTED
    assert resolution.seats_confirmed == 2
    assert resolution.seats_released == 0
    assert resolution.waitlist_status is WaitlistStatus.ACCEPTED


def test_declining_an_offer_releases_its_seats() -> None:
    resolution = resolve_offer_response(
        _offer(seats=2), response=OfferResponse.DECLINE, now=NOW + timedelta(minutes=5)
    )
    assert resolution.state is OfferState.DECLINED
    assert resolution.seats_released == 2
    assert resolution.waitlist_status is WaitlistStatus.DECLINED


def test_accepting_as_the_timer_hits_zero_is_refused_not_raced() -> None:
    """Conservative on purpose: the seat may already have been offered onward."""

    with pytest.raises(CapacityRuleError) as excinfo:
        resolve_offer_response(
            _offer(ttl_minutes=60), response=OfferResponse.ACCEPT, now=NOW + timedelta(minutes=60)
        )
    assert excinfo.value.code == "PROMOTION_OFFER_EXPIRED"


def test_an_already_answered_offer_cannot_be_answered_again() -> None:
    with pytest.raises(CapacityRuleError) as excinfo:
        resolve_offer_response(
            _offer(state=OfferState.ACCEPTED), response=OfferResponse.DECLINE, now=NOW
        )
    assert excinfo.value.code == "PROMOTION_OFFER_NOT_PENDING"


def test_sweeping_an_expired_offer_returns_the_seat_and_the_place() -> None:
    resolution = expire_offer(_offer(seats=2), now=NOW + timedelta(minutes=61))
    assert resolution.state is OfferState.EXPIRED
    assert resolution.seats_released == 2
    assert resolution.waitlist_status is WaitlistStatus.WAITING


def test_a_live_offer_cannot_be_swept() -> None:
    with pytest.raises(CapacityRuleError) as excinfo:
        expire_offer(_offer(), now=NOW + timedelta(minutes=1))
    assert excinfo.value.code == "PROMOTION_OFFER_NOT_EXPIRED"


def test_a_promotion_notification_is_deduped_per_round() -> None:
    first = promotion_dedupe_key(registration_id=_uid(1), round_number=1)
    assert first == promotion_dedupe_key(registration_id=_uid(1), round_number=1)
    assert first != promotion_dedupe_key(registration_id=_uid(1), round_number=2)
    with pytest.raises(CapacityRuleError) as excinfo:
        promotion_dedupe_key(registration_id=_uid(1), round_number=0)
    assert excinfo.value.code == "PROMOTION_ROUND_INVALID"
