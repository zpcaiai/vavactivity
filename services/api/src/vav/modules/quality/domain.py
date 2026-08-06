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


# ---------------------------------------------------------------------------
# Bidirectional traceability queries and graph integrity
# ---------------------------------------------------------------------------


def _index_links(
    links: list[TraceLink], *, reverse: bool = False
) -> dict[str, list[TraceLink]]:
    adjacency: dict[str, list[TraceLink]] = {}
    for link in links:
        key = link.target if reverse else link.source
        adjacency.setdefault(key, []).append(link)
    return adjacency


def _validate_relationships(links: list[TraceLink]) -> None:
    for link in links:
        if link.relationship not in TRACE_RELATIONSHIPS:
            raise QualityPolicyError(
                "QUALITY_TRACE_RELATIONSHIP_INVALID",
                f"Trace relationship '{link.relationship}' is not allowed.",
            )


def _walk(
    links: list[TraceLink], *, root_code: str, reverse: bool, max_depth: int | None
) -> tuple[str, ...]:
    _validate_relationships(links)
    adjacency = _index_links(links, reverse=reverse)
    seen = {root_code}
    ordered: list[str] = []
    queue: deque[tuple[str, int]] = deque([(root_code, 0)])
    while queue:
        code, depth = queue.popleft()
        if max_depth is not None and depth >= max_depth:
            continue
        for link in adjacency.get(code, []):
            neighbour = link.source if reverse else link.target
            if neighbour in seen:
                continue
            seen.add(neighbour)
            ordered.append(neighbour)
            queue.append((neighbour, depth + 1))
    return tuple(ordered)


def traceability_downstream(
    links: list[TraceLink], *, root_code: str, max_depth: int | None = None
) -> tuple[str, ...]:
    """Answer 'what does this node lead to' (requirement -> ... -> evidence)."""

    return _walk(links, root_code=root_code, reverse=False, max_depth=max_depth)


def traceability_upstream(
    links: list[TraceLink], *, root_code: str, max_depth: int | None = None
) -> tuple[str, ...]:
    """Answer 'what depends on this node' (table -> ... -> requirement)."""

    return _walk(links, root_code=root_code, reverse=True, max_depth=max_depth)


def detect_trace_cycles(links: list[TraceLink]) -> tuple[tuple[str, ...], ...]:
    """Return every elementary cycle entry path found in the trace graph.

    Trace graphs must stay acyclic: a cycle means an artifact transitively
    justifies itself, which would let an unimplemented requirement look
    verified.
    """

    _validate_relationships(links)
    adjacency = _index_links(links)
    colour: dict[str, int] = {}
    cycles: list[tuple[str, ...]] = []
    nodes = sorted({link.source for link in links} | {link.target for link in links})

    def visit(node: str, path: list[str]) -> None:
        colour[node] = 1
        path.append(node)
        for link in sorted(adjacency.get(node, []), key=lambda item: item.target):
            target = link.target
            state = colour.get(target, 0)
            if state == 1:
                cycles.append(tuple(path[path.index(target) :] + [target]))
            elif state == 0:
                visit(target, path)
        path.pop()
        colour[node] = 2

    for node in nodes:
        if colour.get(node, 0) == 0:
            visit(node, [])
    return tuple(sorted(set(cycles)))


def detect_dangling_links(
    nodes: list[TraceNode], links: list[TraceLink]
) -> tuple[tuple[str, str, str], ...]:
    """Return links whose source or target node is not registered."""

    _validate_relationships(links)
    known = {node.code for node in nodes}
    dangling = [
        (link.source, link.target, link.relationship)
        for link in links
        if link.source not in known or link.target not in known
    ]
    return tuple(sorted(set(dangling)))


def unreachable_nodes(
    nodes: list[TraceNode], links: list[TraceLink], *, root_codes: list[str]
) -> tuple[str, ...]:
    """Nodes that no declared root can reach: candidate orphan artifacts."""

    reachable: set[str] = set()
    for root in root_codes:
        reachable.add(root)
        reachable.update(traceability_downstream(links, root_code=root))
    return tuple(sorted({node.code for node in nodes} - reachable))


# ---------------------------------------------------------------------------
# Gap and orphan detection
# ---------------------------------------------------------------------------


class GapType(StrEnum):
    UNIMPLEMENTED_REQUIREMENT = "unimplemented_requirement"
    UNVERIFIED_REQUIREMENT = "unverified_requirement"
    ORPHAN_PAGE = "orphan_page"
    ORPHAN_API = "orphan_api"
    ORPHAN_EVENT = "orphan_event"
    ORPHAN_PERMISSION = "orphan_permission"
    ORPHAN_TABLE = "orphan_table"
    MISSING_ADMIN_CAPABILITY = "missing_admin_capability"
    MISSING_EXCEPTION_PATH = "missing_exception_path"
    MISSING_TEST = "missing_test"
    MISSING_METRIC = "missing_metric"
    MISSING_AUDIT = "missing_audit"
    MISSING_PERMISSION = "missing_permission"
    MISSING_RETENTION_POLICY = "missing_retention_policy"
    MISSING_ERASURE_PATH = "missing_erasure_path"
    MISSING_NOTIFICATION = "missing_notification"
    MISSING_SECURITY_CHECK = "missing_security_check"
    MISSING_EVIDENCE = "missing_evidence"
    UNCONSUMED_EVENT = "unconsumed_event"
    UNRESOLVED_DEAD_LETTER = "unresolved_dead_letter"
    UNTESTED_STATE = "untested_state"
    BROKEN_TRACE_LINK = "broken_trace_link"
    TRACE_CYCLE = "trace_cycle"
    INCOMPLETE_BUSINESS_FLOW = "incomplete_business_flow"


@dataclass(frozen=True)
class QualityFinding:
    """A deterministic, addressable quality gap."""

    gap_code: str
    gap_type: GapType
    severity: QualityCriticality
    subject: str
    detection_rule_code: str
    description: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "gap_code": self.gap_code,
            "gap_type": self.gap_type.value,
            "severity": self.severity.value,
            "subject": self.subject,
            "detection_rule_code": self.detection_rule_code,
            "description": self.description,
        }


def _slug(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "-", value.upper()).strip("-")


def _finding(
    gap_type: GapType,
    subject: str,
    severity: QualityCriticality | str,
    rule: str,
    description: str,
) -> QualityFinding:
    return QualityFinding(
        gap_code=f"GAP-{_slug(gap_type.value)}-{_slug(subject)}",
        gap_type=gap_type,
        severity=QualityCriticality(severity),
        subject=subject,
        detection_rule_code=rule,
        description=description,
    )


@dataclass(frozen=True)
class PageArtifact:
    code: str
    application: str
    route_path: str
    criticality: QualityCriticality = QualityCriticality.NORMAL
    has_navigation_entry: bool = False
    inbound_references: tuple[str, ...] = ()
    query_apis: tuple[str, ...] = ()
    command_apis: tuple[str, ...] = ()
    required_permissions: tuple[str, ...] = ()
    is_public: bool = False
    tests: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApiArtifact:
    code: str
    method: str
    path: str
    module: str
    criticality: QualityCriticality = QualityCriticality.NORMAL
    is_command: bool = False
    is_public: bool = False
    sensitive: bool = False
    callers: tuple[str, ...] = ()
    internal_purpose: str | None = None
    permissions: tuple[str, ...] = ()
    audited: bool = False
    idempotent: bool = False
    error_contract: bool = False
    tests: tuple[str, ...] = ()


@dataclass(frozen=True)
class EventArtifact:
    code: str
    criticality: QualityCriticality = QualityCriticality.NORMAL
    publishers: tuple[str, ...] = ()
    consumers: tuple[str, ...] = ()
    audit_only: bool = False
    inbox_deduplicated: bool = False


@dataclass(frozen=True)
class PermissionArtifact:
    code: str
    referencing_routes: tuple[str, ...] = ()
    referencing_services: tuple[str, ...] = ()


@dataclass(frozen=True)
class TableArtifact:
    code: str
    module: str
    criticality: QualityCriticality = QualityCriticality.NORMAL
    has_repository: bool = False
    retention_policy: str | None = None
    data_owner: str | None = None
    holds_personal_data: bool = False
    erasure_path: str | None = None


@dataclass(frozen=True)
class StateMachineArtifact:
    code: str
    module: str
    criticality: QualityCriticality = QualityCriticality.NORMAL
    states: tuple[str, ...] = ()
    tested_states: tuple[str, ...] = ()
    terminal_states: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapabilityArtifact:
    code: str
    capability_type: CapabilityType
    criticality: QualityCriticality = QualityCriticality.NORMAL
    admin_capabilities: tuple[str, ...] = ()
    exception_scenarios: tuple[str, ...] = ()
    metrics: tuple[str, ...] = ()
    notifications: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    audited: bool = False
    permissions: tuple[str, ...] = ()


@dataclass(frozen=True)
class DeadLetterArtifact:
    queue: str
    open_count: int
    criticality: QualityCriticality = QualityCriticality.NORMAL


@dataclass(frozen=True)
class RequirementArtifact:
    code: str
    criticality: QualityCriticality = QualityCriticality.NORMAL
    status: QualityRequirementStatus = QualityRequirementStatus.DRAFT
    capabilities: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    owner_team: str | None = None


@dataclass(frozen=True)
class ArtifactInventory:
    requirements: tuple[RequirementArtifact, ...] = ()
    capabilities: tuple[CapabilityArtifact, ...] = ()
    pages: tuple[PageArtifact, ...] = ()
    apis: tuple[ApiArtifact, ...] = ()
    events: tuple[EventArtifact, ...] = ()
    permissions: tuple[PermissionArtifact, ...] = ()
    tables: tuple[TableArtifact, ...] = ()
    state_machines: tuple[StateMachineArtifact, ...] = ()
    dead_letters: tuple[DeadLetterArtifact, ...] = ()


def detect_orphan_pages(pages: list[PageArtifact]) -> tuple[QualityFinding, ...]:
    """A route with no navigation entry, business jump or deep link is orphaned."""

    return tuple(
        _finding(
            GapType.ORPHAN_PAGE,
            page.code,
            page.criticality,
            "RULE-ORPHAN-PAGE",
            f"Page {page.code} ({page.route_path}) has no navigation entry or inbound reference.",
        )
        for page in pages
        if not page.has_navigation_entry and not page.inbound_references
    )


def detect_mock_only_pages(pages: list[PageArtifact]) -> tuple[QualityFinding, ...]:
    """A page that calls no API cannot change or read persistent state."""

    return tuple(
        _finding(
            GapType.ORPHAN_PAGE,
            f"{page.code}-mock-only",
            page.criticality,
            "RULE-MOCK-ONLY-PAGE",
            f"Page {page.code} declares no query or command API and cannot prove backend state.",
        )
        for page in pages
        if not page.query_apis and not page.command_apis
    )


def detect_orphan_apis(apis: list[ApiArtifact]) -> tuple[QualityFinding, ...]:
    """A production API with no caller, consumer or declared internal purpose."""

    return tuple(
        _finding(
            GapType.ORPHAN_API,
            api.code,
            api.criticality,
            "RULE-ORPHAN-API",
            f"API {api.method} {api.path} has no caller and no declared internal purpose.",
        )
        for api in apis
        if not api.callers and not api.internal_purpose
    )


def detect_missing_permissions(apis: list[ApiArtifact]) -> tuple[QualityFinding, ...]:
    """Sensitive or command APIs must declare a permission or be explicitly public."""

    findings: list[QualityFinding] = []
    for api in apis:
        if api.permissions or api.is_public:
            continue
        if api.is_command or api.sensitive:
            findings.append(
                _finding(
                    GapType.MISSING_PERMISSION,
                    api.code,
                    QualityCriticality.BLOCKER if api.sensitive else api.criticality,
                    "RULE-MISSING-PERMISSION",
                    f"API {api.method} {api.path} is not public but declares no permission.",
                )
            )
    return tuple(findings)


def detect_missing_audit(apis: list[ApiArtifact]) -> tuple[QualityFinding, ...]:
    """Administrative and high-risk writes must be audited."""

    return tuple(
        _finding(
            GapType.MISSING_AUDIT,
            api.code,
            api.criticality,
            "RULE-MISSING-AUDIT",
            f"Write API {api.method} {api.path} does not record an audit event.",
        )
        for api in apis
        if api.is_command and not api.audited
    )


def detect_missing_idempotency(apis: list[ApiArtifact]) -> tuple[QualityFinding, ...]:
    """Command APIs without an idempotency strategy cannot survive retries."""

    return tuple(
        _finding(
            GapType.MISSING_SECURITY_CHECK,
            f"{api.code}-idempotency",
            api.criticality,
            "RULE-MISSING-IDEMPOTENCY",
            f"Command API {api.method} {api.path} declares no idempotency strategy.",
        )
        for api in apis
        if api.is_command and not api.idempotent
    )


def detect_orphan_events(events: list[EventArtifact]) -> tuple[QualityFinding, ...]:
    """Published events with no consumer and no declared audit purpose."""

    return tuple(
        _finding(
            GapType.ORPHAN_EVENT,
            event.code,
            event.criticality,
            "RULE-ORPHAN-EVENT",
            f"Event {event.code} is published but has no consumer and no audit purpose.",
        )
        for event in events
        if event.publishers and not event.consumers and not event.audit_only
    )


def detect_unconsumed_events(events: list[EventArtifact]) -> tuple[QualityFinding, ...]:
    """Consumers must deduplicate through an inbox before side effects."""

    return tuple(
        _finding(
            GapType.UNCONSUMED_EVENT,
            f"{event.code}-inbox",
            event.criticality,
            "RULE-CONSUMER-WITHOUT-INBOX",
            f"Event {event.code} has consumers but no inbox deduplication.",
        )
        for event in events
        if event.consumers and not event.inbox_deduplicated
    )


def detect_orphan_permissions(
    permissions: list[PermissionArtifact],
) -> tuple[QualityFinding, ...]:
    """Registered permissions that no route or service references."""

    return tuple(
        _finding(
            GapType.ORPHAN_PERMISSION,
            permission.code,
            QualityCriticality.MAJOR,
            "RULE-ORPHAN-PERMISSION",
            f"Permission {permission.code} is registered but never enforced.",
        )
        for permission in permissions
        if not permission.referencing_routes and not permission.referencing_services
    )


def detect_orphan_tables(tables: list[TableArtifact]) -> tuple[QualityFinding, ...]:
    """Tables with no repository, retention policy or data owner."""

    findings: list[QualityFinding] = []
    for table in tables:
        if not table.has_repository and not table.data_owner:
            findings.append(
                _finding(
                    GapType.ORPHAN_TABLE,
                    table.code,
                    table.criticality,
                    "RULE-ORPHAN-TABLE",
                    f"Table {table.code} has neither a repository nor a data owner.",
                )
            )
        if not table.retention_policy:
            findings.append(
                _finding(
                    GapType.MISSING_RETENTION_POLICY,
                    table.code,
                    table.criticality,
                    "RULE-MISSING-RETENTION-POLICY",
                    f"Table {table.code} declares no retention policy.",
                )
            )
    return tuple(findings)


def detect_missing_erasure_paths(tables: list[TableArtifact]) -> tuple[QualityFinding, ...]:
    """Personal data must have an executable deletion path."""

    return tuple(
        _finding(
            GapType.MISSING_ERASURE_PATH,
            table.code,
            QualityCriticality.BLOCKER,
            "RULE-MISSING-ERASURE-PATH",
            f"Table {table.code} stores personal data but declares no erasure path.",
        )
        for table in tables
        if table.holds_personal_data and not table.erasure_path
    )


def detect_untested_states(
    machines: list[StateMachineArtifact],
) -> tuple[QualityFinding, ...]:
    """Every declared state must be exercised by at least one test."""

    findings: list[QualityFinding] = []
    for machine in machines:
        tested = set(machine.tested_states)
        for state in machine.states:
            if state not in tested:
                findings.append(
                    _finding(
                        GapType.UNTESTED_STATE,
                        f"{machine.code}-{state}",
                        machine.criticality,
                        "RULE-UNTESTED-STATE",
                        f"State '{state}' of {machine.code} has no test coverage.",
                    )
                )
    return tuple(findings)


def detect_unreachable_terminal_states(
    machines: list[StateMachineArtifact],
) -> tuple[QualityFinding, ...]:
    """A state machine without declared terminal states can strand business data."""

    return tuple(
        _finding(
            GapType.INCOMPLETE_BUSINESS_FLOW,
            f"{machine.code}-terminal",
            QualityCriticality.BLOCKER,
            "RULE-NO-TERMINAL-STATE",
            f"State machine {machine.code} declares no terminal state.",
        )
        for machine in machines
        if machine.states and not machine.terminal_states
    )


def detect_missing_admin_capabilities(
    capabilities: list[CapabilityArtifact],
) -> tuple[QualityFinding, ...]:
    """Every user action must have an administrator counterpart."""

    return tuple(
        _finding(
            GapType.MISSING_ADMIN_CAPABILITY,
            capability.code,
            capability.criticality,
            "RULE-MISSING-ADMIN-CAPABILITY",
            f"Capability {capability.code} has no administrator handling path.",
        )
        for capability in capabilities
        if capability.capability_type is CapabilityType.USER_ACTION
        and not capability.admin_capabilities
    )


def detect_missing_exception_paths(
    capabilities: list[CapabilityArtifact],
) -> tuple[QualityFinding, ...]:
    """Blocker and critical capabilities must register exception scenarios."""

    return tuple(
        _finding(
            GapType.MISSING_EXCEPTION_PATH,
            capability.code,
            capability.criticality,
            "RULE-MISSING-EXCEPTION-PATH",
            f"Capability {capability.code} registers no exception scenario.",
        )
        for capability in capabilities
        if capability.criticality in RELEASE_CRITICAL and not capability.exception_scenarios
    )


def detect_missing_metrics(
    capabilities: list[CapabilityArtifact],
) -> tuple[QualityFinding, ...]:
    """Asynchronous work without metrics cannot be operated."""

    return tuple(
        _finding(
            GapType.MISSING_METRIC,
            capability.code,
            capability.criticality,
            "RULE-MISSING-METRIC",
            f"Asynchronous capability {capability.code} exposes no metric.",
        )
        for capability in capabilities
        if capability.capability_type in ASYNC_CAPABILITY_TYPES and not capability.metrics
    )


def detect_missing_notifications(
    capabilities: list[CapabilityArtifact],
) -> tuple[QualityFinding, ...]:
    """Critical user-visible outcomes must reach the user."""

    return tuple(
        _finding(
            GapType.MISSING_NOTIFICATION,
            capability.code,
            capability.criticality,
            "RULE-MISSING-NOTIFICATION",
            f"Capability {capability.code} declares no notification for its outcome.",
        )
        for capability in capabilities
        if capability.criticality in RELEASE_CRITICAL
        and capability.capability_type
        in {CapabilityType.USER_ACTION, CapabilityType.SYSTEM_PROCESS}
        and not capability.notifications
    )


def detect_missing_tests(
    requirements: list[RequirementArtifact],
) -> tuple[QualityFinding, ...]:
    return tuple(
        _finding(
            GapType.MISSING_TEST,
            requirement.code,
            requirement.criticality,
            "RULE-MISSING-TEST",
            f"Requirement {requirement.code} has no automated test.",
        )
        for requirement in requirements
        if requirement.criticality in RELEASE_CRITICAL and not requirement.tests
    )


def detect_missing_evidence(
    requirements: list[RequirementArtifact],
) -> tuple[QualityFinding, ...]:
    return tuple(
        _finding(
            GapType.MISSING_EVIDENCE,
            requirement.code,
            requirement.criticality,
            "RULE-MISSING-EVIDENCE",
            f"Requirement {requirement.code} has no acceptance evidence.",
        )
        for requirement in requirements
        if requirement.criticality in RELEASE_CRITICAL and not requirement.evidence
    )


def detect_unimplemented_requirements(
    requirements: list[RequirementArtifact],
) -> tuple[QualityFinding, ...]:
    findings: list[QualityFinding] = []
    implemented = {
        QualityRequirementStatus.IMPLEMENTED,
        QualityRequirementStatus.VERIFIED,
    }
    for requirement in requirements:
        if requirement.status not in implemented or not requirement.capabilities:
            findings.append(
                _finding(
                    GapType.UNIMPLEMENTED_REQUIREMENT,
                    requirement.code,
                    requirement.criticality,
                    "RULE-UNIMPLEMENTED-REQUIREMENT",
                    f"Requirement {requirement.code} is not mapped to an implemented capability.",
                )
            )
        elif requirement.status is not QualityRequirementStatus.VERIFIED:
            findings.append(
                _finding(
                    GapType.UNVERIFIED_REQUIREMENT,
                    requirement.code,
                    requirement.criticality,
                    "RULE-UNVERIFIED-REQUIREMENT",
                    f"Requirement {requirement.code} is implemented but not verified.",
                )
            )
    return tuple(findings)


def detect_unresolved_dead_letters(
    dead_letters: list[DeadLetterArtifact],
) -> tuple[QualityFinding, ...]:
    return tuple(
        _finding(
            GapType.UNRESOLVED_DEAD_LETTER,
            item.queue,
            item.criticality,
            "RULE-UNRESOLVED-DEAD-LETTER",
            f"Queue {item.queue} holds {item.open_count} unresolved dead letters.",
        )
        for item in dead_letters
        if item.open_count > 0
    )


def detect_missing_owners(
    requirements: list[RequirementArtifact],
) -> tuple[QualityFinding, ...]:
    return tuple(
        _finding(
            GapType.MISSING_EVIDENCE,
            f"{requirement.code}-owner",
            requirement.criticality,
            "RULE-MISSING-OWNER",
            f"Requirement {requirement.code} has no owning team.",
        )
        for requirement in requirements
        if requirement.criticality in RELEASE_CRITICAL and not requirement.owner_team
    )


GAP_DETECTORS: tuple[tuple[str, Any], ...] = (
    ("requirements", detect_unimplemented_requirements),
    ("requirements", detect_missing_tests),
    ("requirements", detect_missing_evidence),
    ("requirements", detect_missing_owners),
    ("pages", detect_orphan_pages),
    ("pages", detect_mock_only_pages),
    ("apis", detect_orphan_apis),
    ("apis", detect_missing_permissions),
    ("apis", detect_missing_audit),
    ("apis", detect_missing_idempotency),
    ("events", detect_orphan_events),
    ("events", detect_unconsumed_events),
    ("permissions", detect_orphan_permissions),
    ("tables", detect_orphan_tables),
    ("tables", detect_missing_erasure_paths),
    ("state_machines", detect_untested_states),
    ("state_machines", detect_unreachable_terminal_states),
    ("capabilities", detect_missing_admin_capabilities),
    ("capabilities", detect_missing_exception_paths),
    ("capabilities", detect_missing_metrics),
    ("capabilities", detect_missing_notifications),
    ("dead_letters", detect_unresolved_dead_letters),
)


def detect_all_gaps(inventory: ArtifactInventory) -> tuple[QualityFinding, ...]:
    """Run every deterministic detector and return unique findings by gap code."""

    collected: dict[str, QualityFinding] = {}
    for attribute, detector in GAP_DETECTORS:
        for finding in detector(list(getattr(inventory, attribute))):
            collected.setdefault(finding.gap_code, finding)
    return tuple(sorted(collected.values(), key=lambda item: item.gap_code))


def critical_findings(
    findings: tuple[QualityFinding, ...] | list[QualityFinding],
) -> tuple[QualityFinding, ...]:
    return tuple(item for item in findings if item.severity in RELEASE_CRITICAL)


# ---------------------------------------------------------------------------
# Business closure matrix
# ---------------------------------------------------------------------------


CLOSURE_DIMENSIONS: tuple[str, ...] = (
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


@dataclass(frozen=True)
class BusinessClosureRow:
    flow_code: str
    criticality: QualityCriticality
    dimensions: dict[str, bool]


@dataclass(frozen=True)
class ClosureEvaluation:
    flow_code: str
    criticality: QualityCriticality
    complete: bool
    missing_dimensions: tuple[str, ...]
    unknown_dimensions: tuple[str, ...]

    def as_finding(self) -> QualityFinding | None:
        if self.complete:
            return None
        return _finding(
            GapType.INCOMPLETE_BUSINESS_FLOW,
            self.flow_code,
            self.criticality,
            "RULE-INCOMPLETE-BUSINESS-FLOW",
            f"Flow {self.flow_code} is missing: {', '.join(self.missing_dimensions)}.",
        )


def evaluate_business_closure(row: BusinessClosureRow) -> ClosureEvaluation:
    """Evaluate one business line against the ten mandatory closure dimensions.

    Fail closed: an absent dimension key counts as missing, never as satisfied.
    """

    validate_code(row.flow_code, FLOW_CODE_PATTERN, "Business flow")
    unknown = tuple(sorted(set(row.dimensions) - set(CLOSURE_DIMENSIONS)))
    missing = tuple(
        dimension for dimension in CLOSURE_DIMENSIONS if not row.dimensions.get(dimension, False)
    )
    return ClosureEvaluation(
        flow_code=row.flow_code,
        criticality=row.criticality,
        complete=not missing and not unknown,
        missing_dimensions=missing,
        unknown_dimensions=unknown,
    )


def evaluate_closure_matrix(
    rows: list[BusinessClosureRow],
) -> tuple[ClosureEvaluation, ...]:
    return tuple(evaluate_business_closure(row) for row in rows)


def closure_ratio(
    evaluations: tuple[ClosureEvaluation, ...] | list[ClosureEvaluation],
    *,
    only_critical: bool = True,
) -> float:
    scope = [
        item
        for item in evaluations
        if not only_critical or item.criticality in RELEASE_CRITICAL
    ]
    if not scope:
        return 0.0
    return round(sum(item.complete for item in scope) / len(scope), 6)


# ---------------------------------------------------------------------------
# Evidence validity
# ---------------------------------------------------------------------------


class QualityEvidenceStatus(StrEnum):
    GENERATED = "generated"
    VALIDATED = "validated"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class EvidenceRecord:
    code: str
    evidence_type: QualityEvidenceType
    status: QualityEvidenceStatus
    release_version: str
    git_commit: str
    environment: str
    checksum_sha256: str
    generated_at: datetime
    expires_at: datetime | None = None
    summary: dict[str, Any] | None = None


def evidence_rejection_reasons(
    evidence: EvidenceRecord,
    *,
    release_version: str,
    git_commit: str,
    environment: str,
    accepted_types: frozenset[QualityEvidenceType],
    now: datetime | None = None,
    recomputed_checksum: str | None = None,
) -> tuple[str, ...]:
    """Return why this evidence cannot support a gate; empty means usable.

    Evidence is bound to a release, a commit and an environment; expired,
    unaccepted, tampered or cross-release evidence never satisfies a gate.
    """

    current = now or datetime.now(UTC)
    reasons: list[str] = []
    if evidence.status is not QualityEvidenceStatus.ACCEPTED:
        reasons.append("evidence_not_accepted")
    if evidence.evidence_type not in accepted_types:
        reasons.append("evidence_type_not_accepted_by_gate")
    if evidence.release_version != release_version:
        reasons.append("evidence_release_mismatch")
    if evidence.git_commit != git_commit:
        reasons.append("evidence_commit_mismatch")
    if evidence.environment != environment:
        reasons.append("evidence_environment_mismatch")
    if evidence.generated_at.tzinfo is None or current.tzinfo is None:
        reasons.append("evidence_timestamp_not_timezone_aware")
    if evidence.expires_at is not None and evidence.expires_at <= current:
        reasons.append("evidence_expired")
    if not re.fullmatch(r"[0-9a-f]{64}", evidence.checksum_sha256 or ""):
        reasons.append("evidence_checksum_missing")
    elif recomputed_checksum is not None and recomputed_checksum != evidence.checksum_sha256:
        reasons.append("evidence_checksum_mismatch")
    if not evidence.summary:
        reasons.append("evidence_summary_empty")
    return tuple(sorted(set(reasons)))


def select_gate_evidence(
    records: list[EvidenceRecord],
    *,
    metric: str,
    release_version: str,
    git_commit: str,
    environment: str,
    accepted_types: frozenset[QualityEvidenceType],
    now: datetime | None = None,
) -> tuple[Any, tuple[str, ...]]:
    """Pick the observed value for a gate metric, or explain the failure.

    Fail closed: with no usable evidence the observed value is ``None`` and the
    gate must be treated as failed rather than skipped.
    """

    reasons: list[str] = []
    usable = []
    for record in records:
        record_reasons = evidence_rejection_reasons(
            record,
            release_version=release_version,
            git_commit=git_commit,
            environment=environment,
            accepted_types=accepted_types,
            now=now,
        )
        if record_reasons:
            reasons.extend(record_reasons)
            continue
        usable.append(record)
    for record in sorted(usable, key=lambda item: item.generated_at, reverse=True):
        summary = record.summary or {}
        if metric in summary:
            return summary[metric], ()
    if not usable:
        return None, tuple(sorted(set(reasons)) or ("required_current_evidence_missing",))
    return None, ("gate_metric_absent_from_evidence",)


# ---------------------------------------------------------------------------
# Structural completeness scoring
# ---------------------------------------------------------------------------


STRUCTURAL_SCORE_WEIGHTS: dict[str, int] = {
    "requirement_trace_coverage": 20,
    "capability_implementation_mapping": 15,
    "business_closure": 20,
    "exception_path_coverage": 15,
    "admin_support": 10,
    "test_and_evidence": 15,
    "ownership_and_documentation": 5,
}


@dataclass(frozen=True)
class ScoreComponent:
    dimension: str
    weight: int
    ratio: float
    counted: bool
    points: float
    reason: str | None = None


@dataclass(frozen=True)
class StructuralScore:
    total: float
    components: tuple[ScoreComponent, ...]
    vetoes: tuple[NonWaivableFailure, ...]
    decision: ReleaseQualityDecision

    @property
    def blocked(self) -> bool:
        return self.decision is ReleaseQualityDecision.NO_GO


def score_structural_completeness(
    ratios: dict[str, float],
    *,
    verifiable: dict[str, bool] | None = None,
    vetoes: list[NonWaivableFailure] | tuple[NonWaivableFailure, ...] = (),
    gate_outcomes: list[GateOutcome] | None = None,
) -> StructuralScore:
    """Weighted structural completeness with an unconditional veto rule.

    A dimension only scores when the caller can prove a verifiable artifact
    exists: declarations, test names without results and screenshots without
    backend state are worth zero. Any non-waivable failure forces ``NO_GO``
    regardless of the total, so a high score can never mask a critical defect.
    """

    unknown = sorted(set(ratios) - set(STRUCTURAL_SCORE_WEIGHTS))
    if unknown:
        raise QualityPolicyError(
            "QUALITY_SCORE_DIMENSION_UNKNOWN",
            f"Unknown structural score dimension(s): {', '.join(unknown)}.",
        )
    proof = verifiable or {}
    components: list[ScoreComponent] = []
    total = 0.0
    for dimension, weight in STRUCTURAL_SCORE_WEIGHTS.items():
        raw = ratios.get(dimension)
        if raw is None:
            components.append(
                ScoreComponent(dimension, weight, 0.0, False, 0.0, "dimension_not_reported")
            )
            continue
        if not 0.0 <= float(raw) <= 1.0:
            raise QualityPolicyError(
                "QUALITY_SCORE_RATIO_INVALID",
                f"Ratio for '{dimension}' must be between 0 and 1.",
            )
        counted = proof.get(dimension, True)
        points = round(weight * float(raw), 6) if counted else 0.0
        components.append(
            ScoreComponent(
                dimension,
                weight,
                float(raw),
                counted,
                points,
                None if counted else "no_verifiable_artifact",
            )
        )
        total += points
    veto_list = tuple(dict.fromkeys(NonWaivableFailure(item) for item in vetoes))
    decision = ReleaseQualityDecision.GO
    if gate_outcomes is not None:
        decision = release_decision(list(gate_outcomes))
    if veto_list:
        decision = ReleaseQualityDecision.NO_GO
    return StructuralScore(round(total, 6), tuple(components), veto_list, decision)


def structural_ratios_from_findings(
    inventory: ArtifactInventory,
    findings: tuple[QualityFinding, ...] | list[QualityFinding],
) -> dict[str, float]:
    """Derive scoring ratios from detected gaps against the inventory size."""

    def ratio(total: int, failed: int) -> float:
        if total <= 0:
            return 0.0
        return round(max(0.0, (total - failed)) / total, 6)

    by_type: dict[GapType, int] = {}
    for finding in findings:
        by_type[finding.gap_type] = by_type.get(finding.gap_type, 0) + 1
    requirements = len(inventory.requirements)
    capabilities = len(inventory.capabilities)
    return {
        "requirement_trace_coverage": ratio(
            requirements, by_type.get(GapType.UNIMPLEMENTED_REQUIREMENT, 0)
        ),
        "capability_implementation_mapping": ratio(
            capabilities, by_type.get(GapType.MISSING_ADMIN_CAPABILITY, 0)
        ),
        "exception_path_coverage": ratio(
            capabilities, by_type.get(GapType.MISSING_EXCEPTION_PATH, 0)
        ),
        "admin_support": ratio(capabilities, by_type.get(GapType.MISSING_ADMIN_CAPABILITY, 0)),
        "test_and_evidence": ratio(
            requirements,
            by_type.get(GapType.MISSING_TEST, 0) + by_type.get(GapType.MISSING_EVIDENCE, 0),
        ),
        "ownership_and_documentation": ratio(
            requirements, by_type.get(GapType.UNVERIFIED_REQUIREMENT, 0)
        ),
    }
