from uuid import UUID

import pytest

from vav.common.exceptions import VavError
from vav.modules.activities.domain import (
    ActivityStatus,
    RegistrationStatus,
    deterministic_groups,
    ensure_activity_transition,
    ensure_registration_transition,
    waitlist_order_key,
)


def test_activity_and_registration_happy_paths_are_explicit() -> None:
    ensure_activity_transition(ActivityStatus.DRAFT, ActivityStatus.IN_REVIEW)
    ensure_activity_transition(ActivityStatus.IN_REVIEW, ActivityStatus.PUBLISHED)
    ensure_registration_transition(RegistrationStatus.STARTED, RegistrationStatus.PENDING_PAYMENT)
    ensure_registration_transition(RegistrationStatus.PENDING_PAYMENT, RegistrationStatus.CONFIRMED)


def test_browser_return_cannot_confirm_a_registration() -> None:
    with pytest.raises(VavError) as raised:
        ensure_registration_transition(
            RegistrationStatus.PENDING_PAYMENT, RegistrationStatus.STARTED
        )
    assert raised.value.code == "REGISTRATION_STATE_TRANSITION_INVALID"


def test_grouping_is_reproducible_and_assigns_each_registration_once() -> None:
    ids = [UUID(int=value) for value in range(1, 18)]
    first = deterministic_groups(ids, target_size=4, seed="event-2026")
    second = deterministic_groups(list(reversed(ids)), target_size=4, seed="event-2026")
    assert first == second
    assert sorted(item for group in first for item in group) == ids
    assert max(map(len, first)) == 4


def test_in_progress_activity_requires_incident_flow_for_cancellation() -> None:
    with pytest.raises(VavError) as raised:
        ensure_activity_transition(ActivityStatus.IN_PROGRESS, ActivityStatus.CANCELLED)
    assert raised.value.code == "ACTIVITY_STATE_TRANSITION_INVALID"


def test_waitlist_order_is_priority_then_explicit_override_then_sequence() -> None:
    rows = [
        {"priority_score": 0, "manual_order_override": None, "sequence_number": 1},
        {"priority_score": 0, "manual_order_override": 1, "sequence_number": 9},
        {"priority_score": 1, "manual_order_override": None, "sequence_number": 20},
    ]
    ordered = sorted(rows, key=lambda row: waitlist_order_key(**row))
    assert [row["sequence_number"] for row in ordered] == [20, 9, 1]
