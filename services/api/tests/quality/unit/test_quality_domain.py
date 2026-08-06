from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from vav.modules.quality.domain import (
    BUSINESS_CLOSURE_KEYS,
    GateEnforcementLevel,
    GateOutcome,
    QualityGateStatus,
    QualityPolicyError,
    ReleaseQualityDecision,
    TraceLink,
    TraceNode,
    TraceNodeType,
    analyze_traceability,
    business_flow_complete,
    evaluate_gate_condition,
    release_decision,
    validate_waiver,
)


def test_traceability_requires_reachable_types_and_verified_links() -> None:
    nodes = [
        TraceNode("REQ-1", TraceNodeType.REQUIREMENT),
        TraceNode("CAP-1", TraceNodeType.CAPABILITY),
        TraceNode("TEST-1", TraceNodeType.TEST),
    ]
    incomplete = analyze_traceability(
        nodes,
        [TraceLink("REQ-1", "CAP-1", "implements", verified=False)],
        root_code="REQ-1",
        required_types=frozenset({TraceNodeType.CAPABILITY, TraceNodeType.TEST}),
    )
    assert not incomplete.complete
    assert incomplete.missing_required_targets == ("test",)
    assert incomplete.unverified_links

    complete = analyze_traceability(
        nodes,
        [
            TraceLink("REQ-1", "CAP-1", "implements", verified=True),
            TraceLink("CAP-1", "TEST-1", "verified_by", verified=True),
        ],
        root_code="REQ-1",
        required_types=frozenset({TraceNodeType.CAPABILITY, TraceNodeType.TEST}),
    )
    assert complete.complete


@pytest.mark.parametrize(
    ("operator", "observed", "expected"),
    [("eq", 1, 1), ("gte", 1.0, 1.0), ("contains", ["pass"], "pass")],
)
def test_restricted_gate_dsl(operator: str, observed: object, expected: object) -> None:
    assert evaluate_gate_condition(
        {"metric": "quality_metric", "operator": operator, "expected": expected}, observed
    )


def test_gate_dsl_rejects_code_sql_and_unknown_fields() -> None:
    for condition in (
        {"metric": "x; DROP TABLE users", "operator": "eq", "expected": 0},
        {"metric": "safe_metric", "operator": "python", "expected": "__import__('os')"},
        {"metric": "safe_metric", "operator": "eq", "expected": 1, "sql": "SELECT 1"},
    ):
        with pytest.raises(QualityPolicyError):
            evaluate_gate_condition(condition, 1)


def test_release_decision_is_fail_closed() -> None:
    assert release_decision([]) is ReleaseQualityDecision.NO_GO
    assert (
        release_decision(
            [GateOutcome("GATE-ONE", GateEnforcementLevel.BLOCKER, QualityGateStatus.FAILED)]
        )
        is ReleaseQualityDecision.NO_GO
    )
    assert (
        release_decision(
            [
                GateOutcome(
                    "GATE-ONE",
                    GateEnforcementLevel.REQUIRED,
                    QualityGateStatus.WAIVED,
                    waiver_valid=True,
                )
            ]
        )
        is ReleaseQualityDecision.CONDITIONAL_GO
    )


def test_nonwaivable_and_self_approved_waivers_are_rejected() -> None:
    now = datetime.now(UTC)
    with pytest.raises(QualityPolicyError, match="non-waivable"):
        validate_waiver(
            gate_code="GATE-SECURITY-CRITICAL",
            requested_by="a",
            approved_by="b",
            valid_from=now - timedelta(minutes=1),
            expires_at=now + timedelta(days=1),
            mitigation_conditions={"owner": "security"},
            now=now,
        )
    with pytest.raises(QualityPolicyError, match="independent"):
        validate_waiver(
            gate_code="GATE-OPTIONAL-ONE",
            requested_by="a",
            approved_by="a",
            valid_from=now - timedelta(minutes=1),
            expires_at=now + timedelta(days=1),
            mitigation_conditions={"owner": "quality"},
            now=now,
        )


def test_business_closure_is_closed_world() -> None:
    assert business_flow_complete(dict.fromkeys(BUSINESS_CLOSURE_KEYS, True))
    with pytest.raises(QualityPolicyError):
        business_flow_complete({"entry": True})
