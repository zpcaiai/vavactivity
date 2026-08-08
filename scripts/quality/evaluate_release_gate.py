#!/usr/bin/env python3
"""Offline release-gate evaluator for the VAV quality control plane.

Reads a declarative evaluation request (artifact inventory, business-closure
matrix, gate outcomes and non-waivable failures), runs the pure Batch 21 domain
algorithms and prints a reproducible Go / Conditional-Go / No-Go decision.

The evaluator never touches the database or the network, so a release decision
can be reproduced from a stored request document. It fails closed: a missing
section is treated as absent evidence, not as a pass.

Usage:
    python scripts/quality/evaluate_release_gate.py request.json
    python scripts/quality/evaluate_release_gate.py --self-check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/api/src"))

from vav.modules.quality.domain import (  # noqa: E402
    ApiArtifact,
    ArtifactInventory,
    BusinessClosureRow,
    CapabilityArtifact,
    CapabilityType,
    DeadLetterArtifact,
    EventArtifact,
    GateEnforcementLevel,
    GateOutcome,
    NonWaivableFailure,
    PageArtifact,
    PermissionArtifact,
    QualityCriticality,
    QualityGateStatus,
    QualityPolicyError,
    QualityRequirementStatus,
    RequirementArtifact,
    StateMachineArtifact,
    TableArtifact,
    closure_ratio,
    critical_findings,
    detect_all_gaps,
    evaluate_closure_matrix,
    score_structural_completeness,
    structural_ratios_from_findings,
)

SELF_CHECK_REQUEST: dict[str, Any] = {
    "release_version": "2026.08.0-rc.1",
    "environment": "staging",
    "inventory": {
        "requirements": [
            {
                "code": "REQ-VAV-QUALITY-001",
                "criticality": "blocker",
                "status": "approved",
            }
        ],
        "pages": [
            {
                "code": "PAGE-ADMIN-QUALITY",
                "application": "admin-web",
                "route_path": "/q",
            }
        ],
    },
    "closure_matrix": [
        {
            "flow_code": "FLOW-COMMERCE-PURCHASE",
            "criticality": "blocker",
            "dimensions": {"entry": True},
        }
    ],
    "gate_outcomes": [
        {
            "code": "GATE-REQ-BLOCKER-COVERAGE",
            "enforcement": "blocker",
            "status": "failed",
        }
    ],
    "non_waivable_failures": [],
}


def _enum_field(raw: dict[str, Any], key: str, enum: Any, default: Any) -> Any:
    value = raw.get(key)
    return default if value is None else enum(value)


def _tuple(raw: dict[str, Any], key: str) -> tuple[str, ...]:
    return tuple(raw.get(key) or ())


def _requirement(raw: dict[str, Any]) -> RequirementArtifact:
    return RequirementArtifact(
        code=raw["code"],
        criticality=_enum_field(
            raw, "criticality", QualityCriticality, QualityCriticality.NORMAL
        ),
        status=_enum_field(
            raw, "status", QualityRequirementStatus, QualityRequirementStatus.DRAFT
        ),
        capabilities=_tuple(raw, "capabilities"),
        tests=_tuple(raw, "tests"),
        evidence=_tuple(raw, "evidence"),
        owner_team=raw.get("owner_team"),
    )


def _capability(raw: dict[str, Any]) -> CapabilityArtifact:
    return CapabilityArtifact(
        code=raw["code"],
        capability_type=CapabilityType(raw.get("capability_type", "user_action")),
        criticality=_enum_field(
            raw, "criticality", QualityCriticality, QualityCriticality.NORMAL
        ),
        admin_capabilities=_tuple(raw, "admin_capabilities"),
        exception_scenarios=_tuple(raw, "exception_scenarios"),
        metrics=_tuple(raw, "metrics"),
        notifications=_tuple(raw, "notifications"),
        tests=_tuple(raw, "tests"),
        evidence=_tuple(raw, "evidence"),
        audited=bool(raw.get("audited", False)),
        permissions=_tuple(raw, "permissions"),
    )


def _page(raw: dict[str, Any]) -> PageArtifact:
    return PageArtifact(
        code=raw["code"],
        application=raw["application"],
        route_path=raw["route_path"],
        criticality=_enum_field(
            raw, "criticality", QualityCriticality, QualityCriticality.NORMAL
        ),
        has_navigation_entry=bool(raw.get("has_navigation_entry", False)),
        inbound_references=_tuple(raw, "inbound_references"),
        query_apis=_tuple(raw, "query_apis"),
        command_apis=_tuple(raw, "command_apis"),
        required_permissions=_tuple(raw, "required_permissions"),
        is_public=bool(raw.get("is_public", False)),
        tests=_tuple(raw, "tests"),
    )


def _api(raw: dict[str, Any]) -> ApiArtifact:
    return ApiArtifact(
        code=raw["code"],
        method=raw["method"],
        path=raw["path"],
        module=raw["module"],
        criticality=_enum_field(
            raw, "criticality", QualityCriticality, QualityCriticality.NORMAL
        ),
        is_command=bool(raw.get("is_command", False)),
        is_public=bool(raw.get("is_public", False)),
        sensitive=bool(raw.get("sensitive", False)),
        callers=_tuple(raw, "callers"),
        internal_purpose=raw.get("internal_purpose"),
        permissions=_tuple(raw, "permissions"),
        audited=bool(raw.get("audited", False)),
        idempotent=bool(raw.get("idempotent", False)),
        error_contract=bool(raw.get("error_contract", False)),
        tests=_tuple(raw, "tests"),
    )


def _event(raw: dict[str, Any]) -> EventArtifact:
    return EventArtifact(
        code=raw["code"],
        criticality=_enum_field(
            raw, "criticality", QualityCriticality, QualityCriticality.NORMAL
        ),
        publishers=_tuple(raw, "publishers"),
        consumers=_tuple(raw, "consumers"),
        audit_only=bool(raw.get("audit_only", False)),
        inbox_deduplicated=bool(raw.get("inbox_deduplicated", False)),
    )


def _permission(raw: dict[str, Any]) -> PermissionArtifact:
    return PermissionArtifact(
        code=raw["code"],
        referencing_routes=_tuple(raw, "referencing_routes"),
        referencing_services=_tuple(raw, "referencing_services"),
    )


def _table(raw: dict[str, Any]) -> TableArtifact:
    return TableArtifact(
        code=raw["code"],
        module=raw["module"],
        criticality=_enum_field(
            raw, "criticality", QualityCriticality, QualityCriticality.NORMAL
        ),
        has_repository=bool(raw.get("has_repository", False)),
        retention_policy=raw.get("retention_policy"),
        data_owner=raw.get("data_owner"),
        holds_personal_data=bool(raw.get("holds_personal_data", False)),
        erasure_path=raw.get("erasure_path"),
    )


def _state_machine(raw: dict[str, Any]) -> StateMachineArtifact:
    return StateMachineArtifact(
        code=raw["code"],
        module=raw["module"],
        criticality=_enum_field(
            raw, "criticality", QualityCriticality, QualityCriticality.NORMAL
        ),
        states=_tuple(raw, "states"),
        tested_states=_tuple(raw, "tested_states"),
        terminal_states=_tuple(raw, "terminal_states"),
    )


def _dead_letter(raw: dict[str, Any]) -> DeadLetterArtifact:
    return DeadLetterArtifact(
        queue=raw["queue"],
        open_count=int(raw.get("open_count", 0)),
        criticality=_enum_field(
            raw, "criticality", QualityCriticality, QualityCriticality.NORMAL
        ),
    )


BUILDERS: dict[str, Any] = {
    "requirements": _requirement,
    "capabilities": _capability,
    "pages": _page,
    "apis": _api,
    "events": _event,
    "permissions": _permission,
    "tables": _table,
    "state_machines": _state_machine,
    "dead_letters": _dead_letter,
}


def build_inventory(raw: dict[str, Any]) -> ArtifactInventory:
    return ArtifactInventory(
        **{
            key: tuple(builder(item) for item in raw.get(key) or [])
            for key, builder in BUILDERS.items()
        }
    )


def build_closure_rows(raw: list[dict[str, Any]]) -> list[BusinessClosureRow]:
    return [
        BusinessClosureRow(
            flow_code=item["flow_code"],
            criticality=QualityCriticality(item.get("criticality", "normal")),
            dimensions=dict(item.get("dimensions") or {}),
        )
        for item in raw
    ]


def build_gate_outcomes(raw: list[dict[str, Any]]) -> list[GateOutcome]:
    return [
        GateOutcome(
            code=item["code"],
            enforcement=GateEnforcementLevel(item.get("enforcement", "blocker")),
            status=QualityGateStatus(item.get("status", "pending")),
            waiver_valid=bool(item.get("waiver_valid", False)),
        )
        for item in raw
    ]


def evaluate(request: dict[str, Any]) -> dict[str, Any]:
    inventory = build_inventory(request.get("inventory") or {})
    findings = detect_all_gaps(inventory)
    closure = evaluate_closure_matrix(
        build_closure_rows(request.get("closure_matrix") or [])
    )
    ratios = structural_ratios_from_findings(inventory, findings)
    ratios["business_closure"] = closure_ratio(closure)
    outcomes = build_gate_outcomes(request.get("gate_outcomes") or [])
    vetoes = [
        NonWaivableFailure(item) for item in request.get("non_waivable_failures") or []
    ]
    score = score_structural_completeness(ratios, vetoes=vetoes, gate_outcomes=outcomes)
    return {
        "release_version": request.get("release_version"),
        "environment": request.get("environment"),
        "decision": score.decision.value,
        "structural_score": score.total,
        "vetoes": [item.value for item in score.vetoes],
        "critical_gap_count": len(critical_findings(findings)),
        "gap_count": len(findings),
        "critical_business_closure_ratio": ratios["business_closure"],
        "incomplete_flows": [item.flow_code for item in closure if not item.complete],
        "components": [
            {
                "dimension": item.dimension,
                "weight": item.weight,
                "ratio": item.ratio,
                "counted": item.counted,
                "points": item.points,
                "reason": item.reason,
            }
            for item in score.components
        ],
        "findings": [item.as_dict() for item in findings],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", nargs="?", help="path to a JSON evaluation request")
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="evaluate the built-in fail-closed fixture instead of a file",
    )
    parser.add_argument(
        "--expect-decision",
        choices=("go", "conditional_go", "no_go"),
        help="return success only when the evaluated decision matches this value",
    )
    args = parser.parse_args(argv)
    if args.self_check:
        request = SELF_CHECK_REQUEST
    elif args.request:
        request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    else:
        parser.error("provide a request file or --self-check")
        return 2
    try:
        result = evaluate(request)
    except (KeyError, ValueError, QualityPolicyError) as exc:
        print(json.dumps({"decision": "no_go", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.expect_decision is not None:
        return 0 if result["decision"] == args.expect_decision else 1
    return 0 if result["decision"] == "go" else 1


if __name__ == "__main__":
    raise SystemExit(main())
