"""Repeated and concurrent evaluations must produce identical decisions."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from vav.modules.quality.domain import (
    ApiArtifact,
    ArtifactInventory,
    BusinessClosureRow,
    CapabilityArtifact,
    CapabilityType,
    CLOSURE_DIMENSIONS,
    GateEnforcementLevel,
    GateOutcome,
    PageArtifact,
    QualityCriticality,
    QualityGateStatus,
    QualityRequirementStatus,
    ReleaseQualityDecision,
    RequirementArtifact,
    detect_all_gaps,
    evaluate_closure_matrix,
    release_decision,
    score_structural_completeness,
    structural_ratios_from_findings,
)

INVENTORY = ArtifactInventory(
    requirements=tuple(
        RequirementArtifact(
            code=f"REQ-VAV-QUALITY-{index:03d}",
            criticality=QualityCriticality.BLOCKER,
            status=QualityRequirementStatus.APPROVED,
        )
        for index in range(1, 21)
    ),
    capabilities=tuple(
        CapabilityArtifact(
            code=f"CAP-QUALITY-ITEM-{index}",
            capability_type=CapabilityType.USER_ACTION,
            criticality=QualityCriticality.CRITICAL,
        )
        for index in range(1, 11)
    ),
    pages=tuple(
        PageArtifact(
            code=f"PAGE-{index}", application="admin-web", route_path=f"/p/{index}"
        )
        for index in range(1, 11)
    ),
    apis=tuple(
        ApiArtifact(
            code=f"API-{index}",
            method="POST",
            path=f"/api/v1/x/{index}",
            module="quality",
            is_command=True,
        )
        for index in range(1, 11)
    ),
)

ROWS = [
    BusinessClosureRow(
        flow_code=f"FLOW-QUALITY-CASE-{index}",
        criticality=QualityCriticality.BLOCKER,
        dimensions={dimension: index % 2 == 0 for dimension in CLOSURE_DIMENSIONS},
    )
    for index in range(1, 9)
]


def _pipeline() -> tuple[str, float, str]:
    findings = detect_all_gaps(INVENTORY)
    ratios = structural_ratios_from_findings(INVENTORY, findings)
    score = score_structural_completeness(ratios)
    closure = evaluate_closure_matrix(ROWS)
    decision = release_decision(
        [
            GateOutcome(
                code="GATE-FLOW-CRITICAL-CLOSURE",
                enforcement=GateEnforcementLevel.BLOCKER,
                status=QualityGateStatus.PASSED
                if all(item.complete for item in closure)
                else QualityGateStatus.FAILED,
            )
        ]
    )
    return (
        ",".join(item.gap_code for item in findings),
        score.total,
        decision.value,
    )


def test_pipeline_is_deterministic_across_repeats() -> None:
    assert len({_pipeline() for _ in range(25)}) == 1


def test_pipeline_is_deterministic_across_threads() -> None:
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = set(pool.map(lambda _: _pipeline(), range(32)))
    assert len(results) == 1


def test_incomplete_critical_closure_forces_no_go() -> None:
    _, _, decision = _pipeline()
    assert decision == ReleaseQualityDecision.NO_GO.value
