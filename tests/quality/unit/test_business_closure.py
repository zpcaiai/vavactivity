"""Business closure matrix evaluation."""

from __future__ import annotations

import pytest

from vav.modules.quality.domain import (
    BUSINESS_CLOSURE_KEYS,
    CLOSURE_DIMENSIONS,
    BusinessClosureRow,
    GapType,
    QualityCriticality,
    QualityPolicyError,
    business_flow_complete,
    closure_ratio,
    evaluate_business_closure,
    evaluate_closure_matrix,
)


def _dimensions(**overrides: bool) -> dict[str, bool]:
    values = dict.fromkeys(CLOSURE_DIMENSIONS, True)
    values.update(overrides)
    return values


def test_ten_mandatory_dimensions_are_declared() -> None:
    assert CLOSURE_DIMENSIONS == (
        "entry",
        "in_progress_state",
        "success_terminal",
        "failure_terminal",
        "cancel_terminal",
        "expiry_terminal",
        "manual_intervention",
        "compensation_path",
        "user_visible_state",
        "admin_actionable",
    )


def test_complete_flow_passes() -> None:
    row = BusinessClosureRow(
        flow_code="FLOW-COMMERCE-PURCHASE",
        criticality=QualityCriticality.BLOCKER,
        dimensions=_dimensions(),
    )
    result = evaluate_business_closure(row)
    assert result.complete is True
    assert result.missing_dimensions == ()
    assert result.as_finding() is None


def test_missing_failure_terminal_blocks_closure() -> None:
    row = BusinessClosureRow(
        flow_code="FLOW-COMMERCE-REFUND",
        criticality=QualityCriticality.BLOCKER,
        dimensions=_dimensions(failure_terminal=False, compensation_path=False),
    )
    result = evaluate_business_closure(row)
    assert result.complete is False
    assert result.missing_dimensions == ("failure_terminal", "compensation_path")
    finding = result.as_finding()
    assert finding is not None
    assert finding.gap_type is GapType.INCOMPLETE_BUSINESS_FLOW
    assert finding.severity is QualityCriticality.BLOCKER


def test_absent_dimension_key_fails_closed() -> None:
    partial = _dimensions()
    del partial["admin_actionable"]
    row = BusinessClosureRow(
        flow_code="FLOW-SAFETY-APPEAL",
        criticality=QualityCriticality.CRITICAL,
        dimensions=partial,
    )
    result = evaluate_business_closure(row)
    assert result.complete is False
    assert "admin_actionable" in result.missing_dimensions


def test_unknown_dimension_is_rejected_not_credited() -> None:
    row = BusinessClosureRow(
        flow_code="FLOW-SKILL-INSTALL",
        criticality=QualityCriticality.MAJOR,
        dimensions=_dimensions(looks_fine=True),
    )
    result = evaluate_business_closure(row)
    assert result.unknown_dimensions == ("looks_fine",)
    assert result.complete is False


def test_invalid_flow_code_is_rejected() -> None:
    row = BusinessClosureRow(
        flow_code="commerce purchase",
        criticality=QualityCriticality.MAJOR,
        dimensions=_dimensions(),
    )
    with pytest.raises(QualityPolicyError) as error:
        evaluate_business_closure(row)
    assert error.value.code == "QUALITY_CODE_INVALID"


def test_closure_ratio_counts_only_critical_flows_by_default() -> None:
    rows = [
        BusinessClosureRow(
            "FLOW-AUTH-REGISTRATION", QualityCriticality.BLOCKER, _dimensions()
        ),
        BusinessClosureRow(
            "FLOW-COURSE-COMPLETION",
            QualityCriticality.CRITICAL,
            _dimensions(expiry_terminal=False),
        ),
        BusinessClosureRow(
            "FLOW-SKILL-UPGRADE", QualityCriticality.MINOR, _dimensions(entry=False)
        ),
    ]
    evaluations = evaluate_closure_matrix(rows)
    assert closure_ratio(evaluations) == 0.5
    assert closure_ratio(evaluations, only_critical=False) == round(1 / 3, 6)


def test_closure_ratio_of_empty_scope_fails_closed() -> None:
    assert closure_ratio([]) == 0.0


def test_legacy_closure_checks_still_enforced() -> None:
    checks = dict.fromkeys(BUSINESS_CLOSURE_KEYS, True)
    assert business_flow_complete(checks) is True
    checks["admin_recovery"] = False
    assert business_flow_complete(checks) is False
    del checks["tests"]
    with pytest.raises(QualityPolicyError) as error:
        business_flow_complete(checks)
    assert error.value.code == "QUALITY_FLOW_CHECKS_INCOMPLETE"
