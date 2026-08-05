"""Exposure budgets, visibility thresholds and cooldowns."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from vav.modules.recommendations.exposure import (
    ExposurePolicy,
    can_receive,
    can_show_profile,
    cooldown_active,
    counts_as_visible,
    exposure_coverage_ratio,
    idempotency_key,
    remaining_daily_capacity,
)

POLICY = ExposurePolicy()


def test_daily_receive_capacity_is_bounded() -> None:
    assert remaining_daily_capacity(daily_received_limit=20, current_received_count=5) == 15
    assert remaining_daily_capacity(daily_received_limit=20, current_received_count=25) == 0


def test_a_member_cannot_receive_more_than_the_daily_limit() -> None:
    granted = can_receive(policy=POLICY, current_received_count=18, requested=10)
    assert granted.allowed and granted.remaining_received == 2
    exhausted = can_receive(policy=POLICY, current_received_count=20, requested=1)
    assert not exhausted.allowed
    assert exhausted.reason_code == "daily_received_limit_reached"


def test_popularity_cap_stops_new_exposure_for_a_single_profile() -> None:
    assert can_show_profile(policy=POLICY, shown_count_today=10).allowed
    capped = can_show_profile(policy=POLICY, shown_count_today=50)
    assert not capped.allowed
    assert capped.reason_code == "daily_shown_limit_reached"


def test_repeat_exposure_respects_the_cooldown_window() -> None:
    assert cooldown_active(policy=POLICY, days_since_last_exposure=3)
    assert not cooldown_active(policy=POLICY, days_since_last_exposure=45)
    assert not cooldown_active(policy=POLICY, days_since_last_exposure=None)


def test_a_loaded_card_is_not_a_seen_card() -> None:
    assert not counts_as_visible(exposure_type="card_impression", duration_ms=9_000, policy=POLICY)
    assert not counts_as_visible(exposure_type="card_visible", duration_ms=200, policy=POLICY)
    assert counts_as_visible(exposure_type="card_visible", duration_ms=1_500, policy=POLICY)
    assert counts_as_visible(exposure_type="profile_opened", duration_ms=None, policy=POLICY)


def test_exposure_keys_are_stable_within_a_bucket_and_differ_across_types() -> None:
    viewer, item = uuid4(), uuid4()
    moment = datetime(2026, 8, 4, 10, 0, 5, tzinfo=UTC)
    later = datetime(2026, 8, 4, 10, 0, 40, tzinfo=UTC)
    assert idempotency_key(
        viewer_user_id=viewer,
        recommendation_item_id=item,
        exposure_type="card_visible",
        occurred_at=moment,
    ) == idempotency_key(
        viewer_user_id=viewer,
        recommendation_item_id=item,
        exposure_type="card_visible",
        occurred_at=later,
    )
    assert idempotency_key(
        viewer_user_id=viewer,
        recommendation_item_id=item,
        exposure_type="card_visible",
        occurred_at=moment,
    ) != idempotency_key(
        viewer_user_id=viewer,
        recommendation_item_id=item,
        exposure_type="profile_opened",
        occurred_at=moment,
    )


def test_coverage_ratio_is_bounded() -> None:
    assert exposure_coverage_ratio(exposed_profiles=5, eligible_profiles=10) == 5_000
    assert exposure_coverage_ratio(exposed_profiles=15, eligible_profiles=10) == 10_000
    assert exposure_coverage_ratio(exposed_profiles=1, eligible_profiles=0) == 0
