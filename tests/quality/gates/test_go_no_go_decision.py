"""Blocker / Required / Advisory gate aggregation into Go, Conditional-Go, No-Go."""

from __future__ import annotations

from vav.modules.quality.domain import (
    NON_WAIVABLE_GATE_CODES,
    GateEnforcementLevel,
    GateOutcome,
    QualityGateStatus,
    ReleaseQualityDecision,
    release_decision,
)


def _outcome(
    code: str,
    enforcement: GateEnforcementLevel,
    status: QualityGateStatus,
    *,
    waiver_valid: bool = False,
) -> GateOutcome:
    return GateOutcome(
        code=code, enforcement=enforcement, status=status, waiver_valid=waiver_valid
    )


def test_no_gates_at_all_is_no_go() -> None:
    assert release_decision([]) is ReleaseQualityDecision.NO_GO


def test_all_blocker_and_required_passed_is_go() -> None:
    outcomes = [
        _outcome(
            "GATE-REQ-BLOCKER-COVERAGE",
            GateEnforcementLevel.BLOCKER,
            QualityGateStatus.PASSED,
        ),
        _outcome(
            "GATE-TEST-CRITICAL",
            GateEnforcementLevel.REQUIRED,
            QualityGateStatus.PASSED,
        ),
        _outcome(
            "GATE-UI-ORPHAN-PAGES",
            GateEnforcementLevel.ADVISORY,
            QualityGateStatus.FAILED,
        ),
    ]
    assert release_decision(outcomes) is ReleaseQualityDecision.GO


def test_single_blocker_failure_is_no_go() -> None:
    outcomes = [
        _outcome(
            "GATE-REQ-BLOCKER-COVERAGE",
            GateEnforcementLevel.BLOCKER,
            QualityGateStatus.FAILED,
        ),
        _outcome(
            "GATE-TEST-CRITICAL",
            GateEnforcementLevel.REQUIRED,
            QualityGateStatus.PASSED,
        ),
    ]
    assert release_decision(outcomes) is ReleaseQualityDecision.NO_GO


def test_pending_blocker_is_no_go_fail_closed() -> None:
    outcomes = [
        _outcome(
            "GATE-REQ-BLOCKER-COVERAGE",
            GateEnforcementLevel.BLOCKER,
            QualityGateStatus.PENDING,
        ),
    ]
    assert release_decision(outcomes) is ReleaseQualityDecision.NO_GO


def test_errored_blocker_is_no_go() -> None:
    outcomes = [
        _outcome(
            "GATE-REQ-BLOCKER-COVERAGE",
            GateEnforcementLevel.BLOCKER,
            QualityGateStatus.ERROR,
        ),
    ]
    assert release_decision(outcomes) is ReleaseQualityDecision.NO_GO


def test_waived_blocker_is_still_no_go() -> None:
    outcomes = [
        _outcome(
            "GATE-REQ-BLOCKER-COVERAGE",
            GateEnforcementLevel.BLOCKER,
            QualityGateStatus.WAIVED,
            waiver_valid=True,
        ),
    ]
    assert release_decision(outcomes) is ReleaseQualityDecision.NO_GO


def test_required_gate_with_valid_waiver_is_conditional_go() -> None:
    outcomes = [
        _outcome(
            "GATE-REQ-BLOCKER-COVERAGE",
            GateEnforcementLevel.BLOCKER,
            QualityGateStatus.PASSED,
        ),
        _outcome(
            "GATE-TEST-CRITICAL",
            GateEnforcementLevel.REQUIRED,
            QualityGateStatus.WAIVED,
            waiver_valid=True,
        ),
    ]
    assert release_decision(outcomes) is ReleaseQualityDecision.CONDITIONAL_GO


def test_required_gate_failure_without_waiver_is_no_go() -> None:
    outcomes = [
        _outcome(
            "GATE-REQ-BLOCKER-COVERAGE",
            GateEnforcementLevel.BLOCKER,
            QualityGateStatus.PASSED,
        ),
        _outcome(
            "GATE-TEST-CRITICAL",
            GateEnforcementLevel.REQUIRED,
            QualityGateStatus.FAILED,
        ),
    ]
    assert release_decision(outcomes) is ReleaseQualityDecision.NO_GO


def test_expired_waiver_makes_the_gate_fail_again() -> None:
    expired = _outcome(
        "GATE-TEST-CRITICAL",
        GateEnforcementLevel.REQUIRED,
        QualityGateStatus.FAILED,
        waiver_valid=False,
    )
    outcomes = [
        _outcome(
            "GATE-REQ-BLOCKER-COVERAGE",
            GateEnforcementLevel.BLOCKER,
            QualityGateStatus.PASSED,
        ),
        expired,
    ]
    assert release_decision(outcomes) is ReleaseQualityDecision.NO_GO


def test_advisory_failure_never_hides_a_blocker_failure() -> None:
    outcomes = [
        _outcome(
            "GATE-UI-ORPHAN-PAGES",
            GateEnforcementLevel.ADVISORY,
            QualityGateStatus.PASSED,
        ),
        _outcome(
            "GATE-SECURITY-CRITICAL",
            GateEnforcementLevel.BLOCKER,
            QualityGateStatus.FAILED,
        ),
    ]
    assert release_decision(outcomes) is ReleaseQualityDecision.NO_GO


def test_non_waivable_gate_declared_required_still_forces_no_go() -> None:
    for code in sorted(NON_WAIVABLE_GATE_CODES):
        outcomes = [
            _outcome(
                "GATE-REQ-BLOCKER-COVERAGE",
                GateEnforcementLevel.BLOCKER,
                QualityGateStatus.PASSED,
            ),
            _outcome(
                code,
                GateEnforcementLevel.REQUIRED,
                QualityGateStatus.WAIVED,
                waiver_valid=True,
            ),
        ]
        assert release_decision(outcomes) is ReleaseQualityDecision.NO_GO, code
