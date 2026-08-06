"""Pure quality-governance domain logic.

Everything in this module is deterministic and IO-free so that the release
blocking decisions of the platform (requirement lifecycle, traceability graph
analysis, gap detection, business-closure evaluation, structural completeness
scoring, evidence validity, waiver policy and release-gate evaluation) can be
unit tested without a database, a network or a running application.

The guiding rule of this module is *fail closed*: whenever evidence is absent,
expired, unverifiable or ambiguous, the corresponding check reports failure.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class QualityPolicyError(ValueError):
    """Raised when a quality policy or declarative definition is violated."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Constitution enums
# ---------------------------------------------------------------------------


class QualityCriticality(StrEnum):
    BLOCKER = "blocker"
    CRITICAL = "critical"
    MAJOR = "major"
    NORMAL = "normal"
    MINOR = "minor"


CRITICALITY_ORDER: tuple[QualityCriticality, ...] = (
    QualityCriticality.MINOR,
    QualityCriticality.NORMAL,
    QualityCriticality.MAJOR,
    QualityCriticality.CRITICAL,
    QualityCriticality.BLOCKER,
)

RELEASE_CRITICAL = frozenset({QualityCriticality.BLOCKER, QualityCriticality.CRITICAL})


def criticality_rank(value: QualityCriticality | str) -> int:
    return CRITICALITY_ORDER.index(QualityCriticality(value))


class QualityDimension(StrEnum):
    FUNCTIONAL_CORRECTNESS = "functional_correctness"
    BUSINESS_CLOSURE = "business_closure"
    DATA_INTEGRITY = "data_integrity"
    USABILITY = "usability"
    ADMIN_OPERABILITY = "admin_operability"
    SECURITY_PRIVACY = "security_privacy"
    PERFORMANCE = "performance"
    RESILIENCE = "resilience"
    OBSERVABILITY = "observability"


CRITICAL_QUALITY_DIMENSIONS: frozenset[QualityDimension] = frozenset(
    {
        QualityDimension.FUNCTIONAL_CORRECTNESS,
        QualityDimension.BUSINESS_CLOSURE,
        QualityDimension.DATA_INTEGRITY,
        QualityDimension.ADMIN_OPERABILITY,
        QualityDimension.SECURITY_PRIVACY,
        QualityDimension.PERFORMANCE,
        QualityDimension.RESILIENCE,
        QualityDimension.OBSERVABILITY,
    }
)

DEFINITION_OF_READY: tuple[str, ...] = (
    "requirement_id",
    "business_goal",
    "actor_role",
    "preconditions",
    "success_criteria",
    "failure_behaviour",
    "privacy_classification",
    "permission_requirements",
    "module_dependencies",
    "acceptance_scenarios",
)

DEFINITION_OF_DONE: tuple[str, ...] = (
    "code",
    "migration",
    "api",
    "entry_point",
    "permission",
    "audit",
    "metric",
    "success_test",
    "exception_test",
    "concurrency_boundary_test",
    "security_test",
    "documentation",
    "acceptance_evidence",
)


class NonWaivableFailure(StrEnum):
    CROSS_USER_DATA_LEAK = "cross_user_data_leak"
    BLOCK_BYPASS = "block_bypass"
    CONTACT_DISCLOSURE_VIOLATION = "contact_disclosure_violation"
    UNCONFIRMED_PAYMENT_ENTITLEMENT = "unconfirmed_payment_entitlement"
    UNRECOVERABLE_CRITICAL_DATA = "unrecoverable_critical_data"
    INCOMPLETE_USER_ERASURE = "incomplete_user_erasure"
    UNRECOVERABLE_BUSINESS_STATE = "unrecoverable_business_state"
    CRITICAL_SECURITY_FINDING = "critical_security_finding"
    CRITICAL_SUPPLY_CHAIN_VULNERABILITY = "critical_supply_chain_vulnerability"
    PRODUCTION_SECRET_LEAK = "production_secret_leak"


NON_WAIVABLE_GATE_CODES: frozenset[str] = frozenset(
    {
        "GATE-SECURITY-CRITICAL",
        "GATE-BLOCK-PROPAGATION",
        "GATE-PRIVACY-ERASURE-COMPLETENESS",
        "GATE-PAYMENT-ENTITLEMENT-INTEGRITY",
        "GATE-RESTORE-DRILL",
        "GATE-DATA-CRITICAL-RECONCILIATION",
    }
)


# ---------------------------------------------------------------------------
# Requirement / capability enums and lifecycles
# ---------------------------------------------------------------------------


class QualityRequirementType(StrEnum):
    BUSINESS = "business"
    USER_EXPERIENCE = "user_experience"
    ADMIN_OPERATION = "admin_operation"
    DATA = "data"
    SECURITY = "security"
    PRIVACY = "privacy"
    PERFORMANCE = "performance"
    RELIABILITY = "reliability"
    OBSERVABILITY = "observability"
    DEPLOYMENT = "deployment"
    COMPLIANCE = "compliance"


class QualityRequirementStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    IN_IMPLEMENTATION = "in_implementation"
    IMPLEMENTED = "implemented"
    VERIFIED = "verified"
    DEFERRED = "deferred"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class RequirementSourceType(StrEnum):
    PROJECT_PLAN = "project_plan"
    BATCH_SPECIFICATION = "batch_specification"
    PRODUCT_REQUIREMENT = "product_requirement"
    USER_STORY = "user_story"
    ARCHITECTURE_DECISION = "architecture_decision"
    SECURITY_POLICY = "security_policy"
    PRIVACY_POLICY = "privacy_policy"
    INCIDENT_ACTION = "incident_action"
    REGULATORY_REQUIREMENT = "regulatory_requirement"


REQUIREMENT_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"approved", "deferred", "rejected"}),
    "approved": frozenset({"in_implementation", "deferred", "rejected", "superseded"}),
    "in_implementation": frozenset({"implemented", "deferred", "superseded"}),
    "implemented": frozenset({"verified", "in_implementation", "superseded"}),
    "verified": frozenset({"superseded"}),
    "deferred": frozenset({"approved", "rejected", "superseded"}),
    "rejected": frozenset(),
    "superseded": frozenset(),
}


class CapabilityType(StrEnum):
    USER_ACTION = "user_action"
    ADMIN_ACTION = "admin_action"
    SYSTEM_PROCESS = "system_process"
    EVENT_CONSUMER = "event_consumer"
    SCHEDULED_JOB = "scheduled_job"
    PROVIDER_INTEGRATION = "provider_integration"
    SECURITY_CONTROL = "security_control"
    DATA_RIGHT = "data_right"
    SKILL_CAPABILITY = "skill_capability"


ASYNC_CAPABILITY_TYPES: frozenset[CapabilityType] = frozenset(
    {
        CapabilityType.EVENT_CONSUMER,
        CapabilityType.SCHEDULED_JOB,
        CapabilityType.SYSTEM_PROCESS,
    }
)


class CapabilityLifecycleStatus(StrEnum):
    PLANNED = "planned"
    IN_DEVELOPMENT = "in_development"
    AVAILABLE = "available"
    SUSPENDED = "suspended"
    DEPRECATED = "deprecated"
    RETIRED = "retired"
    CANCELLED = "cancelled"


CAPABILITY_TRANSITIONS: dict[str, frozenset[str]] = {
    "planned": frozenset({"in_development", "cancelled"}),
    "in_development": frozenset({"available", "cancelled"}),
    "available": frozenset({"suspended", "deprecated"}),
    "suspended": frozenset({"available", "deprecated"}),
    "deprecated": frozenset({"retired", "available"}),
    "retired": frozenset(),
    "cancelled": frozenset(),
}

REQUIREMENT_CODE_PATTERN = re.compile(r"^REQ-VAV-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d{3,}$")
CAPABILITY_CODE_PATTERN = re.compile(r"^CAP-[A-Z0-9]+(?:-[A-Z0-9]+)+$")
FLOW_CODE_PATTERN = re.compile(r"^FLOW-[A-Z0-9]+(?:-[A-Z0-9]+)+$")
GATE_CODE_PATTERN = re.compile(r"^GATE-[A-Z0-9]+(?:-[A-Z0-9]+)+$")


def validate_code(value: str, pattern: re.Pattern[str], kind: str) -> str:
    if not pattern.match(value):
        raise QualityPolicyError(
            "QUALITY_CODE_INVALID", f"{kind} code '{value}' does not match the required format."
        )
    return value


def validate_requirement_transition(current: str, target: str) -> None:
    allowed = REQUIREMENT_TRANSITIONS.get(current)
    if allowed is None:
        raise QualityPolicyError(
            "QUALITY_REQUIREMENT_STATE_UNKNOWN", f"Unknown requirement status '{current}'."
        )
    if target not in allowed:
        raise QualityPolicyError(
            "QUALITY_REQUIREMENT_TRANSITION_INVALID",
            f"Requirement cannot move from '{current}' to '{target}'.",
        )


def validate_capability_transition(current: str, target: str) -> None:
    allowed = CAPABILITY_TRANSITIONS.get(current)
    if allowed is None:
        raise QualityPolicyError(
            "QUALITY_CAPABILITY_STATE_UNKNOWN", f"Unknown capability status '{current}'."
        )
    if target not in allowed:
        raise QualityPolicyError(
            "QUALITY_CAPABILITY_TRANSITION_INVALID",
            f"Capability cannot move from '{current}' to '{target}'.",
        )


def canonical_json(payload: Any) -> str:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )


def content_fingerprint(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def next_semantic_version(current: str | None, *, breaking: bool = False) -> str:
    if not current:
        return "1.0.0"
    parts = current.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise QualityPolicyError(
            "QUALITY_VERSION_INVALID", f"Version '{current}' is not a semantic version."
        )
    major, minor, patch = (int(part) for part in parts)
    if breaking:
        return f"{major + 1}.0.0"
    return f"{major}.{minor + 1}.0"


@dataclass
class VersionedUpsert:
    """Result of an idempotent registry upsert."""

    code: str
    version: str
    fingerprint: str
    changed: bool
    previous_version: str | None = None


def plan_versioned_upsert(
    *,
    code: str,
    payload: dict[str, Any],
    existing_version: str | None = None,
    existing_fingerprint: str | None = None,
    breaking: bool = False,
) -> VersionedUpsert:
    """Decide whether a registry write creates a new version.

    Re-importing an identical manifest is a no-op (idempotent); any content
    change produces a new version and preserves the previous one.
    """

    fingerprint = content_fingerprint(payload)
    if existing_fingerprint == fingerprint and existing_version:
        return VersionedUpsert(
            code=code,
            version=existing_version,
            fingerprint=fingerprint,
            changed=False,
            previous_version=existing_version,
        )
    return VersionedUpsert(
        code=code,
        version=next_semantic_version(existing_version, breaking=breaking),
        fingerprint=fingerprint,
        changed=True,
        previous_version=existing_version,
    )


class TraceNodeType(StrEnum):
    REQUIREMENT = "requirement"
    CAPABILITY = "capability"
    BUSINESS_FLOW = "business_flow"
    USER_JOURNEY = "user_journey"
    PAGE = "page"
    COMPONENT = "component"
    API = "api"
    APPLICATION_SERVICE = "application_service"
    DOMAIN_ENTITY = "domain_entity"
    STATE_MACHINE = "state_machine"
    DATABASE_TABLE = "database_table"
    EVENT = "event"
    PERMISSION = "permission"
    CONFIGURATION = "configuration"
    METRIC = "metric"
    TEST = "test"
    EVIDENCE = "evidence"
    RUNBOOK = "runbook"


TRACE_RELATIONSHIPS = frozenset(
    {
        "implements",
        "exposes",
        "invokes",
        "persists_to",
        "publishes",
        "consumes",
        "requires_permission",
        "observed_by",
        "verified_by",
        "evidenced_by",
        "depends_on",
        "compensates",
        "invalidates",
        "documented_by",
    }
)


class ExceptionScenarioType(StrEnum):
    VALIDATION = "validation"
    AUTHORIZATION = "authorization"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"
    TIMEOUT = "timeout"
    EXPIRY = "expiry"
    PROVIDER_FAILURE = "provider_failure"
    PARTIAL_FAILURE = "partial_failure"
    CONCURRENCY = "concurrency"
    SECURITY_RESTRICTION = "security_restriction"
    PRIVACY_RESTRICTION = "privacy_restriction"
    MANUAL_REVIEW = "manual_review"
    DATA_INCONSISTENCY = "data_inconsistency"


class GateEnforcementLevel(StrEnum):
    BLOCKER = "blocker"
    REQUIRED = "required"
    ADVISORY = "advisory"


class QualityGateStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    WAIVED = "waived"
    ERROR = "error"
    EXPIRED = "expired"


class ReleaseQualityDecision(StrEnum):
    GO = "go"
    CONDITIONAL_GO = "conditional_go"
    NO_GO = "no_go"


class QualityEvidenceType(StrEnum):
    UNIT_TEST_REPORT = "unit_test_report"
    INTEGRATION_TEST_REPORT = "integration_test_report"
    E2E_REPORT = "e2e_report"
    VISUAL_REGRESSION_REPORT = "visual_regression_report"
    SECURITY_REPORT = "security_report"
    PERFORMANCE_REPORT = "performance_report"
    DATA_RECONCILIATION_REPORT = "data_reconciliation_report"
    RESTORE_DRILL_REPORT = "restore_drill_report"
    UAT_APPROVAL = "uat_approval"
    TRACE_BUNDLE = "trace_bundle"
    SCREENSHOT = "screenshot"
    VIDEO = "video"
    MANUAL_REVIEW = "manual_review"


@dataclass(frozen=True)
class TraceNode:
    code: str
    node_type: TraceNodeType


@dataclass(frozen=True)
class TraceLink:
    source: str
    target: str
    relationship: str
    required: bool = True
    verified: bool = False


@dataclass(frozen=True)
class TraceAnalysis:
    reachable: frozenset[str]
    missing_required_targets: tuple[str, ...]
    unverified_links: tuple[tuple[str, str, str], ...]

    @property
    def complete(self) -> bool:
        return not self.missing_required_targets and not self.unverified_links


def analyze_traceability(
    nodes: list[TraceNode],
    links: list[TraceLink],
    *,
    root_code: str,
    required_types: frozenset[TraceNodeType],
) -> TraceAnalysis:
    by_code = {node.code: node for node in nodes}
    if len(by_code) != len(nodes) or root_code not in by_code:
        raise QualityPolicyError(
            "QUALITY_TRACE_GRAPH_INVALID", "Trace graph has duplicate nodes or a missing root."
        )
    adjacency: dict[str, list[TraceLink]] = {code: [] for code in by_code}
    for link in links:
        if link.relationship not in TRACE_RELATIONSHIPS:
            raise QualityPolicyError(
                "QUALITY_TRACE_RELATIONSHIP_INVALID", "Trace relationship is not allowed."
            )
        if link.source not in by_code or link.target not in by_code or link.source == link.target:
            raise QualityPolicyError(
                "QUALITY_TRACE_LINK_INVALID", "Trace link references an invalid node."
            )
        adjacency[link.source].append(link)
    reachable = {root_code}
    queue = deque([root_code])
    unverified: list[tuple[str, str, str]] = []
    while queue:
        source = queue.popleft()
        for link in adjacency[source]:
            if link.required and not link.verified:
                unverified.append((link.source, link.target, link.relationship))
            if link.target not in reachable:
                reachable.add(link.target)
                queue.append(link.target)
    reachable_types = {by_code[code].node_type for code in reachable}
    missing = tuple(sorted(item.value for item in required_types - reachable_types))
    return TraceAnalysis(frozenset(reachable), missing, tuple(sorted(set(unverified))))


ALLOWED_GATE_OPERATORS = frozenset(
    {"eq", "neq", "gt", "gte", "lt", "lte", "contains", "all_passed", "none_open"}
)


def evaluate_gate_condition(condition: dict[str, Any], observed: Any) -> bool:
    if set(condition) != {"metric", "operator", "expected"}:
        raise QualityPolicyError(
            "QUALITY_GATE_CONDITION_INVALID", "Gate condition must be a closed definition."
        )
    metric, operator, expected = (
        condition["metric"],
        condition["operator"],
        condition["expected"],
    )
    if not isinstance(metric, str) or not re.fullmatch(r"[a-z][a-z0-9_]{2,127}", metric):
        raise QualityPolicyError("QUALITY_GATE_METRIC_INVALID", "Gate metric is invalid.")
    if operator not in ALLOWED_GATE_OPERATORS:
        raise QualityPolicyError("QUALITY_GATE_OPERATOR_INVALID", "Gate operator is not allowed.")
    try:
        if operator == "eq":
            return bool(observed == expected)
        if operator == "neq":
            return bool(observed != expected)
        if operator == "gt":
            return bool(observed > expected)
        if operator == "gte":
            return bool(observed >= expected)
        if operator == "lt":
            return bool(observed < expected)
        if operator == "lte":
            return bool(observed <= expected)
        if operator == "contains":
            return expected in observed
        if operator == "all_passed":
            return bool(observed) and all(item == "passed" for item in observed)
        return not observed or all(item in {0, "closed", "resolved"} for item in observed)
    except TypeError as exc:
        raise QualityPolicyError(
            "QUALITY_GATE_VALUE_INVALID", "Observed value cannot be evaluated by this operator."
        ) from exc


@dataclass(frozen=True)
class GateOutcome:
    code: str
    enforcement: GateEnforcementLevel
    status: QualityGateStatus
    waiver_valid: bool = False


def release_decision(outcomes: list[GateOutcome]) -> ReleaseQualityDecision:
    if not outcomes:
        return ReleaseQualityDecision.NO_GO
    for outcome in outcomes:
        if (
            outcome.enforcement is GateEnforcementLevel.BLOCKER
            and outcome.status is not QualityGateStatus.PASSED
        ):
            return ReleaseQualityDecision.NO_GO
        if (
            outcome.code in NON_WAIVABLE_GATE_CODES
            and outcome.status is not QualityGateStatus.PASSED
        ):
            return ReleaseQualityDecision.NO_GO
    required = [item for item in outcomes if item.enforcement is GateEnforcementLevel.REQUIRED]
    if any(item.status is QualityGateStatus.FAILED and not item.waiver_valid for item in required):
        return ReleaseQualityDecision.NO_GO
    if any(item.status is QualityGateStatus.WAIVED or item.waiver_valid for item in required):
        return ReleaseQualityDecision.CONDITIONAL_GO
    if any(item.status is not QualityGateStatus.PASSED for item in required):
        return ReleaseQualityDecision.NO_GO
    return ReleaseQualityDecision.GO


def validate_waiver(
    *,
    gate_code: str,
    requested_by: str,
    approved_by: str | None,
    valid_from: datetime,
    expires_at: datetime,
    mitigation_conditions: dict[str, Any],
    now: datetime | None = None,
    max_days: int = 30,
) -> None:
    current = now or datetime.now(UTC)
    if gate_code in NON_WAIVABLE_GATE_CODES:
        raise QualityPolicyError(
            "QUALITY_WAIVER_FORBIDDEN", "This release failure is non-waivable."
        )
    if approved_by is None or requested_by == approved_by:
        raise QualityPolicyError(
            "QUALITY_WAIVER_SEPARATION_REQUIRED", "Waiver requires an independent approver."
        )
    if valid_from.tzinfo is None or expires_at.tzinfo is None or current.tzinfo is None:
        raise QualityPolicyError(
            "QUALITY_WAIVER_TIME_INVALID", "Waiver times must be timezone-aware."
        )
    if expires_at <= max(valid_from, current) or (expires_at - valid_from).days > max_days:
        raise QualityPolicyError("QUALITY_WAIVER_EXPIRY_INVALID", "Waiver duration is invalid.")
    if not mitigation_conditions:
        raise QualityPolicyError(
            "QUALITY_WAIVER_MITIGATION_REQUIRED", "Waiver mitigation conditions are required."
        )


BUSINESS_CLOSURE_KEYS = frozenset(
    {
        "entry",
        "preconditions",
        "persistent_steps",
        "success_terminal",
        "failure_terminal",
        "cancel_or_expire",
        "user_status",
        "admin_recovery",
        "events",
        "notifications",
        "reconciliation",
        "tests",
    }
)


def business_flow_complete(checks: dict[str, bool]) -> bool:
    if set(checks) != BUSINESS_CLOSURE_KEYS:
        raise QualityPolicyError(
            "QUALITY_FLOW_CHECKS_INCOMPLETE", "Business closure checks are incomplete."
        )
    return all(checks.values())
