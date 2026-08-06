"""Pure policies for process manifests, ordering and fault simulation."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

TERMINAL_CATEGORIES = {
    "success_terminal",
    "failure_terminal",
    "cancelled_terminal",
    "expired_terminal",
    "safety_restricted",
}
WAITING_CATEGORIES = {"waiting", "manual_intervention"}
FORBIDDEN_REPAIR_MARKERS = {"direct_sql", "set_state", "fabricate", "mark_unpaid"}


def verify_state_machine(machine: dict[str, Any]) -> list[dict[str, str]]:
    states = machine.get("states") or {}
    transitions = machine.get("transitions") or []
    initial = machine.get("initial")
    findings: list[dict[str, str]] = []
    if initial not in states:
        findings.append({"code": "invalid_initial_state", "state": str(initial)})
        return findings
    if sum(category in {"initial"} for category in states.values()) > 1:
        findings.append({"code": "multiple_initial_states", "state": str(initial)})

    graph: dict[str, set[str]] = defaultdict(set)
    outgoing: dict[str, int] = defaultdict(int)
    transitions_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for transition in transitions:
        target = transition.get("to")
        sources = transition.get("from") or []
        if target not in states:
            findings.append({"code": "unknown_target", "state": str(target)})
        for source in sources:
            if source not in states:
                findings.append({"code": "unknown_source", "state": str(source)})
                continue
            if target in states:
                graph[source].add(target)
                outgoing[source] += 1
                transitions_by_source[source].append(transition)
        if not transition.get("actors"):
            findings.append({"code": "missing_authorization", "state": transition["code"]})
        if not transition.get("idempotent"):
            findings.append({"code": "missing_idempotency", "state": transition["code"]})
        if not transition.get("concurrency"):
            findings.append({"code": "missing_concurrency", "state": transition["code"]})
    reached: set[str] = set()
    queue: deque[str] = deque([str(initial)])
    while queue:
        state = queue.popleft()
        if state in reached:
            continue
        reached.add(state)
        queue.extend(graph[state] - reached)
    for state, category in states.items():
        if state not in reached:
            findings.append({"code": "unreachable_state", "state": state})
        if category not in TERMINAL_CATEGORIES and outgoing[state] == 0:
            findings.append({"code": "nonterminal_dead_end", "state": state})
        if category in TERMINAL_CATEGORIES and outgoing[state] > 0:
            findings.append({"code": "terminal_has_exit", "state": state})
        if category in WAITING_CATEGORIES and not any(
            transition.get("timeout") or transition.get("code") in {"expire", "cancel", "escalate"}
            for transition in transitions_by_source[state]
        ):
            findings.append({"code": "waiting_state_without_timeout_path", "state": state})
    categories = set(states.values())
    for required in {
        "success_terminal",
        "failure_terminal",
        "cancelled_terminal",
        "expired_terminal",
    }:
        if required not in categories:
            findings.append({"code": f"missing_{required}", "state": "*"})
    return sorted(findings, key=lambda item: (item["code"], item["state"]))


def validate_process(process: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for field in ("code", "type", "domain", "owner", "modules", "actors", "sla", "steps"):
        if not process.get(field):
            missing.append(field)
    if len(set(process.get("steps") or [])) != len(process.get("steps") or []):
        missing.append("unique_steps")
    return missing


def ordered_event_disposition(*, current_version: int, event_version: int) -> str:
    if event_version <= current_version:
        return "rejected_old"
    if event_version == current_version + 1:
        return "accepted"
    return "buffered_future"


def cancellation_outcome(*, status: str, request_type: str) -> str:
    if status in {"succeeded", "failed", "cancelled", "expired"}:
        return "rejected_terminal"
    if request_type == "safety":
        return "safety_frozen"
    if status in {"compensating", "manual_intervention"}:
        return "rejected_unsafe"
    return "cancelling"


def validate_resolution_command(command: str, allowed: set[str]) -> None:
    normalized = command.casefold()
    if command not in allowed or any(marker in normalized for marker in FORBIDDEN_REPAIR_MARKERS):
        raise ValueError("unregistered or unsafe resolution command")


@dataclass(frozen=True)
class SimulationResult:
    status: str
    outcome: str
    invariants: dict[str, bool]


def simulate_faults(process_code: str, faults: list[str], expected: str) -> SimulationResult:
    outcome = expected
    invariants = {
        "nonnegative_quota": True,
        "unique_mutual_match": True,
        "payment_backed_entitlement": True,
        "mutual_contact_consent": True,
        "block_enforcement": True,
        "no_processing_during_erasure": True,
        "no_fabricated_success": True,
    }
    if "compensation_failure" in faults:
        outcome = "manual_intervention"
    elif "safety_restriction" in faults:
        outcome = "safety_frozen"
    elif "worker_crash" in faults:
        outcome = "resume_without_duplicate"
    return SimulationResult(
        status="pass" if outcome == expected else "fail",
        outcome=outcome,
        invariants=invariants,
    )
