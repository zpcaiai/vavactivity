from __future__ import annotations

import pytest

from vav.modules.process_governance.domain import (
    cancellation_outcome,
    ordered_event_disposition,
    simulate_faults,
    validate_resolution_command,
    verify_state_machine,
)


def test_state_machine_verifier_accepts_complete_graph() -> None:
    machine = {
        "initial": "new",
        "states": {
            "new": "initial",
            "done": "success_terminal",
            "failed": "failure_terminal",
            "cancelled": "cancelled_terminal",
            "expired": "expired_terminal",
        },
        "transitions": [
            {
                "code": "complete",
                "from": ["new"],
                "to": "done",
                "actors": ["user"],
                "idempotent": True,
                "concurrency": "optimistic_lock",
            },
            {
                "code": "fail",
                "from": ["new"],
                "to": "failed",
                "actors": ["system"],
                "idempotent": True,
                "concurrency": "optimistic_lock",
            },
            {
                "code": "cancel",
                "from": ["new"],
                "to": "cancelled",
                "actors": ["user"],
                "idempotent": True,
                "concurrency": "optimistic_lock",
            },
            {
                "code": "expire",
                "from": ["new"],
                "to": "expired",
                "actors": ["system"],
                "idempotent": True,
                "concurrency": "advisory_lock",
            },
        ],
    }
    assert verify_state_machine(machine) == []


def test_verifier_detects_unreachable_dead_end_and_missing_controls() -> None:
    findings = verify_state_machine(
        {"initial": "new", "states": {"new": "initial", "lost": "active"}, "transitions": []}
    )
    codes = {item["code"] for item in findings}
    assert {"unreachable_state", "nonterminal_dead_end", "missing_success_terminal"}.issubset(codes)


def test_event_ordering_is_fail_closed() -> None:
    assert ordered_event_disposition(current_version=3, event_version=3) == "rejected_old"
    assert ordered_event_disposition(current_version=3, event_version=4) == "accepted"
    assert ordered_event_disposition(current_version=3, event_version=6) == "buffered_future"


def test_safety_cancellation_has_priority_but_terminal_fact_is_final() -> None:
    assert cancellation_outcome(status="running", request_type="safety") == "safety_frozen"
    assert cancellation_outcome(status="succeeded", request_type="safety") == "rejected_terminal"


def test_unregistered_or_direct_repair_is_rejected() -> None:
    with pytest.raises(ValueError):
        validate_resolution_command("direct_sql.set_state", {"direct_sql.set_state"})
    with pytest.raises(ValueError):
        validate_resolution_command("process.unknown", {"process.retry_registered_step"})


def test_fault_simulation_preserves_global_invariants() -> None:
    result = simulate_faults("membership-purchase", ["worker_crash"], "resume_without_duplicate")
    assert result.status == "pass"
    assert all(result.invariants.values())
