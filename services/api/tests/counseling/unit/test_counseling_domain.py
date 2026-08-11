import pytest

from vav.common.exceptions import VavError
from vav.modules.counseling.domain import ensure_appointment_transition


def test_appointment_state_machine_allows_only_declared_transitions() -> None:
    ensure_appointment_transition("pending_review", "time_proposed")
    ensure_appointment_transition("time_proposed", "confirmed")
    ensure_appointment_transition("confirmed", "completed")
    with pytest.raises(VavError) as error:
        ensure_appointment_transition("pending_review", "completed")
    assert error.value.code == "APPOINTMENT_TRANSITION_INVALID"


def test_terminal_appointment_cannot_be_reopened() -> None:
    with pytest.raises(VavError):
        ensure_appointment_transition("cancelled", "confirmed")


@pytest.mark.parametrize("status", ["requested", "pending_review", "manual_review", "confirmed"])
def test_active_appointment_can_be_cancelled_by_operations(status: str) -> None:
    ensure_appointment_transition(status, "cancelled")
