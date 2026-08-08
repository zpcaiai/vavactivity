"""Structural completeness scoring and the veto rule."""

from __future__ import annotations

import pytest

from vav.modules.quality.domain import (
    STRUCTURAL_SCORE_WEIGHTS,
    ArtifactInventory,
    CapabilityArtifact,
    CapabilityType,
    GateEnforcementLevel,
    GateOutcome,
    NonWaivableFailure,
    QualityCriticality,
    QualityGateStatus,
    QualityPolicyError,
    QualityRequirementStatus,
    ReleaseQualityDecision,
    RequirementArtifact,
    detect_all_gaps,
    score_structural_completeness,
    structural_ratios_from_findings,
)

PERFECT = dict.fromkeys(STRUCTURAL_SCORE_WEIGHTS, 1.0)


def test_weights_sum_to_one_hundred() -> None:
    assert sum(STRUCTURAL_SCORE_WEIGHTS.values()) == 100


def test_perfect_structure_scores_one_hundred() -> None:
    score = score_structural_completeness(PERFECT)
    assert score.total == 100.0
    assert score.decision is ReleaseQualityDecision.GO
    assert score.blocked is False


def test_unreported_dimension_scores_zero() -> None:
    ratios = dict(PERFECT)
    del ratios["business_closure"]
    score = score_structural_completeness(ratios)
    assert score.total == 80.0
    component = next(
        item for item in score.components if item.dimension == "business_closure"
    )
    assert component.counted is False
    assert component.reason == "dimension_not_reported"


def test_unverifiable_claim_is_not_counted() -> None:
    score = score_structural_completeness(
        PERFECT, verifiable={"test_and_evidence": False}
    )
    assert score.total == 85.0
    component = next(
        item for item in score.components if item.dimension == "test_and_evidence"
    )
    assert component.points == 0.0
    assert component.reason == "no_verifiable_artifact"


def test_high_score_cannot_mask_a_non_waivable_failure() -> None:
    score = score_structural_completeness(
        PERFECT, vetoes=[NonWaivableFailure.BLOCK_BYPASS]
    )
    assert score.total == 100.0
    assert score.decision is ReleaseQualityDecision.NO_GO
    assert score.blocked is True
    assert score.vetoes == (NonWaivableFailure.BLOCK_BYPASS,)


@pytest.mark.parametrize(
    "failure",
    [
        NonWaivableFailure.CROSS_USER_DATA_LEAK,
        NonWaivableFailure.BLOCK_BYPASS,
        NonWaivableFailure.CONTACT_DISCLOSURE_VIOLATION,
        NonWaivableFailure.UNCONFIRMED_PAYMENT_ENTITLEMENT,
        NonWaivableFailure.UNRECOVERABLE_CRITICAL_DATA,
        NonWaivableFailure.INCOMPLETE_USER_ERASURE,
        NonWaivableFailure.UNRECOVERABLE_BUSINESS_STATE,
        NonWaivableFailure.CRITICAL_SECURITY_FINDING,
    ],
)
def test_every_declared_veto_forces_no_go(failure: NonWaivableFailure) -> None:
    score = score_structural_completeness(
        PERFECT,
        vetoes=[failure],
        gate_outcomes=[
            GateOutcome(
                code="GATE-TEST-CRITICAL",
                enforcement=GateEnforcementLevel.BLOCKER,
                status=QualityGateStatus.PASSED,
            )
        ],
    )
    assert score.decision is ReleaseQualityDecision.NO_GO


def test_gate_outcomes_drive_the_decision_without_veto() -> None:
    score = score_structural_completeness(
        PERFECT,
        gate_outcomes=[
            GateOutcome(
                code="GATE-TEST-CRITICAL",
                enforcement=GateEnforcementLevel.BLOCKER,
                status=QualityGateStatus.FAILED,
            )
        ],
    )
    assert score.decision is ReleaseQualityDecision.NO_GO


def test_unknown_dimension_is_rejected() -> None:
    with pytest.raises(QualityPolicyError) as error:
        score_structural_completeness({"vibes": 1.0})
    assert error.value.code == "QUALITY_SCORE_DIMENSION_UNKNOWN"


def test_out_of_range_ratio_is_rejected() -> None:
    with pytest.raises(QualityPolicyError) as error:
        score_structural_completeness({"business_closure": 1.5})
    assert error.value.code == "QUALITY_SCORE_RATIO_INVALID"


def test_ratios_derived_from_findings_penalise_gaps() -> None:
    inventory = ArtifactInventory(
        requirements=(
            RequirementArtifact(
                code="REQ-VAV-QUALITY-001",
                criticality=QualityCriticality.BLOCKER,
                status=QualityRequirementStatus.APPROVED,
            ),
            RequirementArtifact(
                code="REQ-VAV-QUALITY-002",
                criticality=QualityCriticality.BLOCKER,
                status=QualityRequirementStatus.VERIFIED,
                capabilities=("CAP-QUALITY-EVALUATE",),
                tests=("t",),
                evidence=("e",),
                owner_team="quality_engineering",
            ),
        ),
        capabilities=(
            CapabilityArtifact(
                code="CAP-QUALITY-EVALUATE",
                capability_type=CapabilityType.ADMIN_ACTION,
                criticality=QualityCriticality.BLOCKER,
                exception_scenarios=("EXC-1",),
            ),
        ),
    )
    findings = detect_all_gaps(inventory)
    ratios = structural_ratios_from_findings(inventory, findings)
    assert ratios["requirement_trace_coverage"] == 0.5
    assert ratios["exception_path_coverage"] == 1.0
    score = score_structural_completeness(ratios)
    assert 0.0 < score.total < 100.0
