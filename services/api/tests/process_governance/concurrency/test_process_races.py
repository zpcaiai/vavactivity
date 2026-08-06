from __future__ import annotations

from vav.modules.process_governance.domain import cancellation_outcome, ordered_event_disposition


def test_completion_cancellation_and_expiry_have_one_valid_terminal_outcome() -> None:
    assert cancellation_outcome(status="succeeded", request_type="user") == "rejected_terminal"
    assert cancellation_outcome(status="expired", request_type="user") == "rejected_terminal"
    assert cancellation_outcome(status="running", request_type="user") == "cancelling"


def test_event_gap_never_silently_advances_sequence() -> None:
    assert ordered_event_disposition(current_version=7, event_version=9) == "buffered_future"
