from __future__ import annotations

from vav.modules.data_governance.domain import event_disposition


def test_duplicate_and_future_events_have_stable_dispositions() -> None:
    assert event_disposition(10, 10) == "rejected_old"
    assert event_disposition(10, 12) == "buffered_future"


def test_backfill_counts_never_require_negative_deltas() -> None:
    from vav.modules.data_governance.schemas import BackfillAction

    action = BackfillAction(action="pause", processed_delta=100, success_delta=99, failure_delta=1)
    assert action.processed_delta == action.success_delta + action.failure_delta
