"""Pure regression-assurance domain logic.

Everything in this module is deterministic and IO-free so that the release
blocking decisions of the regression control plane (test-pyramid budgets,
impact analysis and test selection, flaky-test statistics and quarantine
governance, contract compatibility, model-based and property-based test
generation, mutation scoring, visual-baseline governance, test-data isolation
and the final regression release gate) can be unit tested without a database,
a network or a running application.

The guiding rule of this module is *fail closed*: whenever evidence is absent,
expired, unverifiable or ambiguous, the corresponding check reports failure and
the release gate returns ``NO_GO``.  The second rule is *fail open to more
testing*: whenever impact analysis is uncertain, the selected test scope grows
instead of shrinking.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RegressionPolicyError(ValueError):
    """Raised when a regression policy or declarative definition is violated."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------


class RegressionTestLevel(StrEnum):
    STATIC = "static"
    UNIT = "unit"
    COMPONENT = "component"
    CONTRACT = "contract"
    REPOSITORY_INTEGRATION = "repository_integration"
    MODULE_INTEGRATION = "module_integration"
    MODULE_E2E = "module_e2e"
    CROSS_MODULE_E2E = "cross_module_e2e"
    COMPLETE_JOURNEY = "complete_journey"
    NON_FUNCTIONAL = "non_functional"


class TestCriticality(StrEnum):
    BLOCKER = "blocker"
    CRITICAL = "critical"
    MAJOR = "major"
    NORMAL = "normal"
    ADVISORY = "advisory"


class RegressionTestType(StrEnum):
    FUNCTIONAL = "functional"
    CONTRACT = "contract"
    STATE_MACHINE = "state_machine"
    PROPERTY = "property"
    CONCURRENCY = "concurrency"
    VISUAL = "visual"
    ACCESSIBILITY = "accessibility"
    SECURITY = "security"
    PRIVACY = "privacy"
    DATA_INTEGRITY = "data_integrity"
    RECOVERY = "recovery"
    MUTATION = "mutation"


class RegressionTestLifecycleStatus(StrEnum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    QUARANTINE_REQUESTED = "quarantine_requested"
    QUARANTINED = "quarantined"
    DISABLED = "disabled"
    REMOVED = "removed"


class RegressionTestResultStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    FAILED_UNSTABLE = "failed_unstable"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    INFRASTRUCTURE_ERROR = "infrastructure_error"
    ISOLATION_FAILURE = "isolation_failure"


class FlakyTestCategory(StrEnum):
    TIMING = "timing"
    ORDER_DEPENDENCY = "order_dependency"
    SHARED_STATE = "shared_state"
    RANDOMNESS = "randomness"
    EXTERNAL_PROVIDER = "external_provider"
    BROWSER_RENDERING = "browser_rendering"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    CLOCK_TIMEZONE = "clock_timezone"
    EVENTUAL_CONSISTENCY = "eventual_consistency"
    UNKNOWN = "unknown"


class QuarantineState(StrEnum):
    ACTIVE = "active"
    SUSPECT = "suspect"
    QUARANTINED = "quarantined"
    RETIRED = "retired"


class ContractCompatibility(StrEnum):
    COMPATIBLE = "compatible"
    ADDITIVE = "additive"
    BREAKING = "breaking"


class ContractChangeKind(StrEnum):
    FIELD_ADDED_OPTIONAL = "field_added_optional"
    FIELD_ADDED_REQUIRED = "field_added_required"
    FIELD_REMOVED = "field_removed"
    FIELD_TYPE_CHANGED = "field_type_changed"
    FIELD_MADE_REQUIRED = "field_made_required"
    FIELD_MADE_OPTIONAL = "field_made_optional"
    ENUM_VALUE_ADDED = "enum_value_added"
    ENUM_VALUE_REMOVED = "enum_value_removed"
    OPERATION_REMOVED = "operation_removed"
    SENSITIVE_FIELD_UNCLASSIFIED = "sensitive_field_unclassified"


class MutationStatus(StrEnum):
    KILLED = "killed"
    SURVIVED = "survived"
    TIMED_OUT = "timed_out"
    INVALID = "invalid"
    EQUIVALENT = "equivalent"


class VisualDifferenceSeverity(StrEnum):
    NONE = "none"
    TRIVIAL = "trivial"
    MINOR = "minor"
    MAJOR = "major"
    BLOCKER = "blocker"


class VisualReviewState(StrEnum):
    PENDING = "pending"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class GateDecision(StrEnum):
    GO = "go"
    CONDITIONAL_GO = "conditional_go"
    NO_GO = "no_go"


CRITICAL_CRITICALITIES: frozenset[TestCriticality] = frozenset(
    {TestCriticality.BLOCKER, TestCriticality.CRITICAL}
)

PASSING_RESULT_STATUSES: frozenset[RegressionTestResultStatus] = frozenset(
    {RegressionTestResultStatus.PASSED}
)

FAILING_RESULT_STATUSES: frozenset[RegressionTestResultStatus] = frozenset(
    {
        RegressionTestResultStatus.FAILED,
        RegressionTestResultStatus.FAILED_UNSTABLE,
        RegressionTestResultStatus.TIMED_OUT,
        RegressionTestResultStatus.BLOCKED,
        RegressionTestResultStatus.INFRASTRUCTURE_ERROR,
        RegressionTestResultStatus.ISOLATION_FAILURE,
    }
)

SELECTABLE_LIFECYCLE_STATUSES: frozenset[RegressionTestLifecycleStatus] = frozenset(
    {RegressionTestLifecycleStatus.ACTIVE, RegressionTestLifecycleStatus.DEPRECATED}
)

FAST_PYRAMID_LEVELS: tuple[RegressionTestLevel, ...] = (
    RegressionTestLevel.STATIC,
    RegressionTestLevel.UNIT,
    RegressionTestLevel.COMPONENT,
)

SLOW_PYRAMID_LEVELS: tuple[RegressionTestLevel, ...] = (
    RegressionTestLevel.MODULE_E2E,
    RegressionTestLevel.CROSS_MODULE_E2E,
    RegressionTestLevel.COMPLETE_JOURNEY,
)


def _canonical_checksum(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


# ---------------------------------------------------------------------------
# 1. Test-pyramid governance
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PyramidLayerBudget:
    """Count and ratio budget for one layer of the test pyramid."""

    level: RegressionTestLevel
    minimum_count: int = 0
    minimum_ratio: float = 0.0
    maximum_ratio: float = 1.0
    blocking: bool = True

    def __post_init__(self) -> None:
        if self.minimum_count < 0:
            raise RegressionPolicyError(
                "REGRESSION_PYRAMID_BUDGET_INVALID",
                f"{self.level} minimum_count must not be negative.",
            )
        if not 0.0 <= self.minimum_ratio <= self.maximum_ratio <= 1.0:
            raise RegressionPolicyError(
                "REGRESSION_PYRAMID_BUDGET_INVALID",
                f"{self.level} ratio budget must satisfy 0 <= min <= max <= 1.",
            )


@dataclass(frozen=True)
class PyramidViolation:
    code: str
    level: RegressionTestLevel | None
    observed: float
    expected: float
    blocking: bool
    detail: str


@dataclass(frozen=True)
class PyramidEvaluation:
    total_tests: int
    counts: dict[str, int]
    ratios: dict[str, float]
    fast_ratio: float
    slow_ratio: float
    inverted: bool
    violations: tuple[PyramidViolation, ...]

    @property
    def blocking_violations(self) -> tuple[PyramidViolation, ...]:
        return tuple(violation for violation in self.violations if violation.blocking)

    @property
    def status(self) -> str:
        if self.blocking_violations:
            return "blocked"
        if self.violations:
            return "warning"
        return "passed"

    @property
    def passed(self) -> bool:
        return not self.blocking_violations


DEFAULT_PYRAMID_BUDGETS: tuple[PyramidLayerBudget, ...] = (
    PyramidLayerBudget(RegressionTestLevel.UNIT, minimum_count=50, minimum_ratio=0.35),
    PyramidLayerBudget(RegressionTestLevel.COMPONENT, minimum_count=10, minimum_ratio=0.05),
    PyramidLayerBudget(RegressionTestLevel.CONTRACT, minimum_count=8, minimum_ratio=0.03),
    PyramidLayerBudget(
        RegressionTestLevel.MODULE_INTEGRATION, minimum_count=8, minimum_ratio=0.03
    ),
    PyramidLayerBudget(RegressionTestLevel.COMPLETE_JOURNEY, minimum_count=1, maximum_ratio=0.10),
    PyramidLayerBudget(RegressionTestLevel.CROSS_MODULE_E2E, maximum_ratio=0.15),
    PyramidLayerBudget(RegressionTestLevel.MODULE_E2E, maximum_ratio=0.20),
)


def evaluate_test_pyramid(
    counts: Mapping[RegressionTestLevel | str, int],
    budgets: Sequence[PyramidLayerBudget] = DEFAULT_PYRAMID_BUDGETS,
) -> PyramidEvaluation:
    """Evaluate per-layer count and ratio budgets and detect an inverted pyramid.

    An *inverted* pyramid — where slow browser-level tests outnumber fast
    deterministic tests — is always a blocking violation because it makes the
    regression suite too slow and too unstable to gate a release with.
    """

    normalised: dict[str, int] = {level.value: 0 for level in RegressionTestLevel}
    for raw_level, raw_count in counts.items():
        key = str(raw_level)
        if key not in normalised:
            raise RegressionPolicyError(
                "REGRESSION_PYRAMID_LEVEL_UNKNOWN", f"Unknown test level {key!r}."
            )
        if raw_count < 0:
            raise RegressionPolicyError(
                "REGRESSION_PYRAMID_COUNT_INVALID", f"Test count for {key!r} must not be negative."
            )
        normalised[key] = int(raw_count)

    total = sum(normalised.values())
    ratios = {key: _ratio(value, total) for key, value in normalised.items()}
    violations: list[PyramidViolation] = []

    if total == 0:
        violations.append(
            PyramidViolation(
                code="REGRESSION_PYRAMID_EMPTY",
                level=None,
                observed=0.0,
                expected=1.0,
                blocking=True,
                detail="No registered tests: the pyramid cannot certify a release.",
            )
        )

    for budget in budgets:
        key = budget.level.value
        observed_count = normalised[key]
        observed_ratio = ratios[key]
        if observed_count < budget.minimum_count:
            violations.append(
                PyramidViolation(
                    code="REGRESSION_PYRAMID_MINIMUM_COUNT",
                    level=budget.level,
                    observed=float(observed_count),
                    expected=float(budget.minimum_count),
                    blocking=budget.blocking,
                    detail=f"{key} has {observed_count} tests, minimum is {budget.minimum_count}.",
                )
            )
        if total > 0 and observed_ratio < budget.minimum_ratio:
            violations.append(
                PyramidViolation(
                    code="REGRESSION_PYRAMID_MINIMUM_RATIO",
                    level=budget.level,
                    observed=observed_ratio,
                    expected=budget.minimum_ratio,
                    blocking=budget.blocking,
                    detail=f"{key} ratio {observed_ratio} is below {budget.minimum_ratio}.",
                )
            )
        if total > 0 and observed_ratio > budget.maximum_ratio:
            violations.append(
                PyramidViolation(
                    code="REGRESSION_PYRAMID_MAXIMUM_RATIO",
                    level=budget.level,
                    observed=observed_ratio,
                    expected=budget.maximum_ratio,
                    blocking=budget.blocking,
                    detail=f"{key} ratio {observed_ratio} exceeds {budget.maximum_ratio}.",
                )
            )

    fast_ratio = round(sum(ratios[level.value] for level in FAST_PYRAMID_LEVELS), 6)
    slow_ratio = round(sum(ratios[level.value] for level in SLOW_PYRAMID_LEVELS), 6)
    inverted = total > 0 and slow_ratio >= fast_ratio
    if inverted:
        violations.append(
            PyramidViolation(
                code="REGRESSION_PYRAMID_INVERTED",
                level=None,
                observed=slow_ratio,
                expected=fast_ratio,
                blocking=True,
                detail=(
                    f"Slow end-to-end ratio {slow_ratio} is not below fast ratio {fast_ratio}: "
                    "the pyramid is inverted."
                ),
            )
        )

    return PyramidEvaluation(
        total_tests=total,
        counts=normalised,
        ratios=ratios,
        fast_ratio=fast_ratio,
        slow_ratio=slow_ratio,
        inverted=inverted,
        violations=tuple(violations),
    )


# ---------------------------------------------------------------------------
# 2. Test registry, dependency graph and impact analysis
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TestCaseRecord:
    """A registered, machine-readable automated test."""

    test_case_code: str
    suite_code: str
    level: RegressionTestLevel
    test_type: RegressionTestType
    criticality: TestCriticality
    owning_module: str
    owner_team: str = ""
    lifecycle_status: RegressionTestLifecycleStatus = RegressionTestLifecycleStatus.ACTIVE
    mapped_targets: frozenset[str] = frozenset()
    tags: frozenset[str] = frozenset()
    timeout_seconds: int = 60
    isolation_profile_code: str = ""

    @property
    def is_critical(self) -> bool:
        return self.criticality in CRITICAL_CRITICALITIES

    @property
    def is_selectable(self) -> bool:
        return self.lifecycle_status in SELECTABLE_LIFECYCLE_STATUSES


@dataclass(frozen=True)
class RegistryViolation:
    code: str
    test_case_code: str
    detail: str
    blocking: bool = True


def validate_test_registry(
    records: Sequence[TestCaseRecord],
    *,
    required_target_prefixes: frozenset[str] = frozenset({"REQ-", "RISK-", "INV-"}),
) -> tuple[RegistryViolation, ...]:
    """Reject duplicate codes, ownerless critical tests and unmapped critical tests."""

    violations: list[RegistryViolation] = []
    seen: set[str] = set()
    for record in records:
        if record.test_case_code in seen:
            violations.append(
                RegistryViolation(
                    code="REGRESSION_TEST_CODE_DUPLICATE",
                    test_case_code=record.test_case_code,
                    detail="Test case code is registered more than once.",
                )
            )
        seen.add(record.test_case_code)
        if not record.test_case_code.strip():
            violations.append(
                RegistryViolation(
                    code="REGRESSION_TEST_CODE_MISSING",
                    test_case_code=record.test_case_code,
                    detail="Test case code must be a stable non-empty identifier.",
                )
            )
        if record.timeout_seconds <= 0:
            violations.append(
                RegistryViolation(
                    code="REGRESSION_TEST_TIMEOUT_MISSING",
                    test_case_code=record.test_case_code,
                    detail="Every registered test declares an explicit positive timeout.",
                )
            )
        if not record.is_critical:
            continue
        if not record.owner_team.strip():
            violations.append(
                RegistryViolation(
                    code="REGRESSION_CRITICAL_TEST_OWNER_MISSING",
                    test_case_code=record.test_case_code,
                    detail="Critical tests require an owning team.",
                )
            )
        if not record.isolation_profile_code.strip():
            violations.append(
                RegistryViolation(
                    code="REGRESSION_CRITICAL_TEST_ISOLATION_MISSING",
                    test_case_code=record.test_case_code,
                    detail="Critical tests require a declared isolation profile.",
                )
            )
        mapped = any(
            target.startswith(prefix)
            for target in record.mapped_targets
            for prefix in required_target_prefixes
        )
        if not mapped:
            violations.append(
                RegistryViolation(
                    code="REGRESSION_CRITICAL_TEST_MAPPING_MISSING",
                    test_case_code=record.test_case_code,
                    detail="Critical tests map to a requirement, risk or data invariant.",
                )
            )
        if record.lifecycle_status in {
            RegressionTestLifecycleStatus.QUARANTINED,
            RegressionTestLifecycleStatus.DISABLED,
        }:
            violations.append(
                RegistryViolation(
                    code="REGRESSION_CRITICAL_TEST_QUARANTINED",
                    test_case_code=record.test_case_code,
                    detail="Critical tests must not sit in quarantine or be disabled.",
                )
            )
    return tuple(violations)


def detect_unmapped_requirements(
    records: Sequence[TestCaseRecord], critical_requirement_codes: Iterable[str]
) -> tuple[str, ...]:
    """Return critical requirement codes that no active test maps to."""

    covered: set[str] = set()
    for record in records:
        if record.lifecycle_status is not RegressionTestLifecycleStatus.ACTIVE:
            continue
        covered.update(record.mapped_targets)
    return tuple(sorted(code for code in set(critical_requirement_codes) if code not in covered))


def detect_orphan_mappings(
    records: Sequence[TestCaseRecord], removed_test_case_codes: Iterable[str]
) -> tuple[str, ...]:
    """Return requirement codes whose only coverage came from removed tests."""

    removed = set(removed_test_case_codes)
    remaining: set[str] = set()
    orphaned: set[str] = set()
    for record in records:
        if record.test_case_code in removed:
            orphaned.update(record.mapped_targets)
        elif record.lifecycle_status is RegressionTestLifecycleStatus.ACTIVE:
            remaining.update(record.mapped_targets)
    return tuple(sorted(orphaned - remaining))


@dataclass(frozen=True)
class DependencyGraph:
    """Directed dependency graph: ``edges[node]`` are the nodes ``node`` imports."""

    edges: dict[str, frozenset[str]]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Iterable[str]]) -> DependencyGraph:
        edges: dict[str, frozenset[str]] = {}
        for node, dependencies in raw.items():
            edges.setdefault(node, frozenset())
            resolved = frozenset(str(item) for item in dependencies)
            edges[node] = edges[node] | resolved
            for dependency in resolved:
                edges.setdefault(dependency, frozenset())
        return cls(edges=edges)

    @property
    def nodes(self) -> frozenset[str]:
        return frozenset(self.edges)

    def reverse_index(self) -> dict[str, frozenset[str]]:
        """Return ``node -> nodes that depend on it`` (the impact index)."""

        reverse: dict[str, set[str]] = {node: set() for node in self.edges}
        for node, dependencies in self.edges.items():
            for dependency in dependencies:
                reverse.setdefault(dependency, set()).add(node)
        return {node: frozenset(values) for node, values in reverse.items()}

    def _closure(self, seeds: Iterable[str], index: Mapping[str, frozenset[str]]) -> frozenset[str]:
        seen: set[str] = set()
        queue: deque[str] = deque()
        for seed in seeds:
            if seed not in seen:
                seen.add(seed)
                queue.append(seed)
        while queue:
            current = queue.popleft()
            for neighbour in index.get(current, frozenset()):
                if neighbour not in seen:
                    seen.add(neighbour)
                    queue.append(neighbour)
        return frozenset(seen)

    def dependents_closure(self, seeds: Iterable[str]) -> frozenset[str]:
        """Transitive closure of everything that (indirectly) depends on ``seeds``."""

        return self._closure(seeds, self.reverse_index())

    def dependencies_closure(self, seeds: Iterable[str]) -> frozenset[str]:
        """Transitive closure of everything ``seeds`` (indirectly) depend on."""

        return self._closure(seeds, self.edges)

    def unknown_nodes(self, candidates: Iterable[str]) -> frozenset[str]:
        return frozenset(node for node in candidates if node not in self.edges)


@dataclass(frozen=True)
class ImpactRule:
    """Maps a changed-path pattern onto affected modules or a full-suite escalation."""

    pattern: str
    modules: frozenset[str] = frozenset()
    reason: str = ""
    force_full_suite: bool = False

    def matches(self, path: str) -> bool:
        return re.search(self.pattern, path) is not None


@dataclass(frozen=True)
class ChangedPathAnalysis:
    matched_modules: frozenset[str]
    reasons: tuple[str, ...]
    unmatched_paths: tuple[str, ...]
    full_suite_reasons: tuple[str, ...]


def map_changed_paths(
    changed_paths: Sequence[str], rules: Sequence[ImpactRule]
) -> ChangedPathAnalysis:
    modules: set[str] = set()
    reasons: set[str] = set()
    unmatched: list[str] = []
    full_suite: set[str] = set()
    for path in changed_paths:
        matched = False
        for rule in rules:
            if not rule.matches(path):
                continue
            matched = True
            modules.update(rule.modules)
            if rule.reason:
                reasons.add(f"{path} -> {rule.reason}")
            if rule.force_full_suite:
                full_suite.add(f"{path} touches core platform surface ({rule.reason or rule.pattern})")
        if not matched:
            unmatched.append(path)
    return ChangedPathAnalysis(
        matched_modules=frozenset(modules),
        reasons=tuple(sorted(reasons)),
        unmatched_paths=tuple(unmatched),
        full_suite_reasons=tuple(sorted(full_suite)),
    )


@dataclass(frozen=True)
class TestSelection:
    selected_test_case_codes: tuple[str, ...]
    mandatory_test_case_codes: tuple[str, ...]
    excluded_test_case_codes: tuple[str, ...]
    affected_modules: tuple[str, ...]
    escalated_to_full_suite: bool
    escalation_reasons: tuple[str, ...]
    explanations: dict[str, str]
    exclusion_explanations: dict[str, str]

    @property
    def selection_ratio(self) -> float:
        total = len(self.selected_test_case_codes) + len(self.excluded_test_case_codes)
        return _ratio(len(self.selected_test_case_codes), total)


def select_impacted_tests(
    *,
    changed_paths: Sequence[str],
    rules: Sequence[ImpactRule],
    graph: DependencyGraph,
    test_cases: Sequence[TestCaseRecord],
    mandatory_tags: frozenset[str] = frozenset({"smoke"}),
    always_run_blockers: bool = True,
    release_full_suite_required: bool = False,
) -> TestSelection:
    """Select the minimum safe test set for a change, with explanations.

    Safety rules encoded here:

    * an unmatched changed path means the impact graph is incomplete, so the
      selection escalates to the full suite instead of shrinking;
    * a seed module missing from the dependency graph escalates likewise;
    * core-platform paths force a full regression;
    * blockers and smoke-tagged tests always run;
    * quarantined, disabled and removed tests are never selected.
    """

    analysis = map_changed_paths(changed_paths, rules)
    seeds = analysis.matched_modules
    unknown = graph.unknown_nodes(seeds)
    affected = seeds | graph.dependents_closure(seeds - unknown)

    escalation_reasons: list[str] = list(analysis.full_suite_reasons)
    if analysis.unmatched_paths:
        escalation_reasons.append(
            "impact graph incomplete for paths: " + ", ".join(sorted(analysis.unmatched_paths))
        )
    if unknown:
        escalation_reasons.append(
            "dependency graph is missing modules: " + ", ".join(sorted(unknown))
        )
    if release_full_suite_required:
        escalation_reasons.append("release candidate requires the full regression suite")
    if changed_paths and not seeds and not analysis.unmatched_paths:
        escalation_reasons.append("changed paths produced no module attribution")

    escalated = bool(escalation_reasons)

    selected: dict[str, str] = {}
    mandatory: list[str] = []
    excluded: dict[str, str] = {}

    for record in test_cases:
        if not record.is_selectable:
            excluded[record.test_case_code] = f"lifecycle status is {record.lifecycle_status}"
            continue
        is_mandatory = (
            always_run_blockers and record.criticality is TestCriticality.BLOCKER
        ) or bool(record.tags & mandatory_tags)
        if escalated:
            selected[record.test_case_code] = (
                "full-suite escalation: " + escalation_reasons[0]
                if escalation_reasons
                else "full-suite escalation"
            )
        elif is_mandatory:
            selected[record.test_case_code] = "mandatory test: blocker or smoke tagged"
        elif record.owning_module in affected:
            selected[record.test_case_code] = (
                f"module {record.owning_module} is impacted by the change set"
            )
        else:
            excluded[record.test_case_code] = (
                f"module {record.owning_module} is not in the impacted closure"
            )
        if is_mandatory and record.test_case_code in selected:
            mandatory.append(record.test_case_code)

    return TestSelection(
        selected_test_case_codes=tuple(sorted(selected)),
        mandatory_test_case_codes=tuple(sorted(mandatory)),
        excluded_test_case_codes=tuple(sorted(excluded)),
        affected_modules=tuple(sorted(affected)),
        escalated_to_full_suite=escalated,
        escalation_reasons=tuple(escalation_reasons),
        explanations=dict(sorted(selected.items())),
        exclusion_explanations=dict(sorted(excluded.items())),
    )


# ---------------------------------------------------------------------------
# 3. Flaky-test governance
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExecutionRecord:
    """One observed execution attempt of one test case."""

    run_id: str
    status: RegressionTestResultStatus
    executed_at: datetime
    attempt: int = 1
    commit_sha: str = ""
    failure_signature: str | None = None
    shard_id: str = ""


@dataclass(frozen=True)
class FlakeStatistics:
    total_runs: int
    passed_runs: int
    failed_runs: int
    flake_rate: float
    reliability_ratio: float
    alternations: int
    longest_pass_streak: int
    longest_fail_streak: int
    hidden_retry_passes: int
    distinct_failure_signatures: tuple[str, ...]
    dominant_failure_signature: str | None
    distinct_commits: int

    @property
    def is_flaky(self) -> bool:
        return self.alternations > 0 or self.hidden_retry_passes > 0


def compute_flake_statistics(records: Sequence[ExecutionRecord]) -> FlakeStatistics:
    """Derive stability metrics from raw execution history.

    The *first attempt* of every run determines that run's outcome.  Later
    attempts are diagnostic only and can never convert a failure into a pass —
    they are counted as ``hidden_retry_passes`` instead.
    """

    ordered = sorted(records, key=lambda item: (item.executed_at, item.attempt, item.run_id))
    per_run: dict[str, list[ExecutionRecord]] = {}
    order: list[str] = []
    for record in ordered:
        if record.attempt < 1:
            raise RegressionPolicyError(
                "REGRESSION_EXECUTION_ATTEMPT_INVALID", "Execution attempt numbers start at 1."
            )
        if record.run_id not in per_run:
            per_run[record.run_id] = []
            order.append(record.run_id)
        per_run[record.run_id].append(record)

    outcomes: list[bool] = []
    hidden_retry_passes = 0
    signatures: dict[str, int] = {}
    commits: set[str] = set()
    for run_id in order:
        attempts = sorted(per_run[run_id], key=lambda item: item.attempt)
        first = attempts[0]
        first_passed = first.status in PASSING_RESULT_STATUSES
        outcomes.append(first_passed)
        if not first_passed and any(item.status in PASSING_RESULT_STATUSES for item in attempts[1:]):
            hidden_retry_passes += 1
        for attempt in attempts:
            if attempt.failure_signature:
                signatures[attempt.failure_signature] = signatures.get(attempt.failure_signature, 0) + 1
            if attempt.commit_sha:
                commits.add(attempt.commit_sha)

    total = len(outcomes)
    passed = sum(1 for value in outcomes if value)
    failed = total - passed
    alternations = sum(
        1 for index in range(1, total) if outcomes[index] != outcomes[index - 1]
    )

    longest_pass = longest_fail = current_pass = current_fail = 0
    for value in outcomes:
        if value:
            current_pass += 1
            current_fail = 0
        else:
            current_fail += 1
            current_pass = 0
        longest_pass = max(longest_pass, current_pass)
        longest_fail = max(longest_fail, current_fail)

    dominant = max(signatures, key=lambda key: (signatures[key], key)) if signatures else None
    return FlakeStatistics(
        total_runs=total,
        passed_runs=passed,
        failed_runs=failed,
        flake_rate=_ratio(alternations, total - 1) if total > 1 else 0.0,
        reliability_ratio=_ratio(passed, total),
        alternations=alternations,
        longest_pass_streak=longest_pass,
        longest_fail_streak=longest_fail,
        hidden_retry_passes=hidden_retry_passes,
        distinct_failure_signatures=tuple(sorted(signatures)),
        dominant_failure_signature=dominant,
        distinct_commits=len(commits),
    )


FLAKE_SIGNATURE_PATTERNS: tuple[tuple[str, FlakyTestCategory], ...] = (
    (r"order|previous test|leftover|pollut", FlakyTestCategory.ORDER_DEPENDENCY),
    (r"duplicate key|already exists|shared state|unique constraint", FlakyTestCategory.SHARED_STATE),
    (r"timezone|utc offset|clock skew|daylight", FlakyTestCategory.CLOCK_TIMEZONE),
    (r"eventual|not yet visible|projection lag|stale read", FlakyTestCategory.EVENTUAL_CONSISTENCY),
    (r"timeout|timed out|deadline exceeded|wait for", FlakyTestCategory.TIMING),
    (r"seed|random|shuffle", FlakyTestCategory.RANDOMNESS),
    (r"provider|upstream|connection refused|50[23]|gateway", FlakyTestCategory.EXTERNAL_PROVIDER),
    (r"screenshot|pixel|render|element is not visible|locator", FlakyTestCategory.BROWSER_RENDERING),
    (r"out of memory|no space left|too many open files|resource", FlakyTestCategory.RESOURCE_EXHAUSTION),
)


def classify_flake(
    failure_signature: str | None,
    *,
    fails_only_when_reordered: bool = False,
    passes_only_in_isolation: bool = False,
) -> FlakyTestCategory:
    """Classify instability from observed conditions first, signature text second."""

    if fails_only_when_reordered:
        return FlakyTestCategory.ORDER_DEPENDENCY
    if passes_only_in_isolation:
        return FlakyTestCategory.SHARED_STATE
    if not failure_signature:
        return FlakyTestCategory.UNKNOWN
    text = failure_signature.casefold()
    for pattern, category in FLAKE_SIGNATURE_PATTERNS:
        if re.search(pattern, text):
            return category
    return FlakyTestCategory.UNKNOWN


QUARANTINE_TRANSITIONS: dict[QuarantineState, frozenset[QuarantineState]] = {
    QuarantineState.ACTIVE: frozenset({QuarantineState.SUSPECT}),
    QuarantineState.SUSPECT: frozenset({QuarantineState.ACTIVE, QuarantineState.QUARANTINED}),
    QuarantineState.QUARANTINED: frozenset({QuarantineState.ACTIVE, QuarantineState.RETIRED}),
    QuarantineState.RETIRED: frozenset(),
}


def advance_quarantine_state(
    current: QuarantineState, target: QuarantineState
) -> QuarantineState:
    """Validate one step of the quarantine lifecycle state machine."""

    if target not in QUARANTINE_TRANSITIONS[current]:
        raise RegressionPolicyError(
            "REGRESSION_QUARANTINE_TRANSITION_INVALID",
            f"Quarantine transition {current} -> {target} is not allowed.",
        )
    return target


def recommend_quarantine_state(
    statistics: FlakeStatistics,
    *,
    current: QuarantineState = QuarantineState.ACTIVE,
    suspect_flake_rate: float = 0.05,
    quarantine_flake_rate: float = 0.20,
    minimum_runs: int = 5,
    stability_runs_required: int = 10,
) -> QuarantineState:
    """Recommend the next quarantine state from observed stability."""

    if statistics.total_runs < minimum_runs:
        return current
    if current is QuarantineState.QUARANTINED:
        if (
            statistics.longest_pass_streak >= stability_runs_required
            and statistics.flake_rate <= suspect_flake_rate
        ):
            return QuarantineState.ACTIVE
        return QuarantineState.QUARANTINED
    if statistics.flake_rate >= quarantine_flake_rate and current is QuarantineState.SUSPECT:
        return QuarantineState.QUARANTINED
    if statistics.flake_rate > suspect_flake_rate or statistics.hidden_retry_passes:
        return QuarantineState.SUSPECT if current is QuarantineState.ACTIVE else current
    if current is QuarantineState.SUSPECT and statistics.longest_pass_streak >= stability_runs_required:
        return QuarantineState.ACTIVE
    return current


NON_QUARANTINABLE_TAGS: frozenset[str] = frozenset(
    {
        "payment",
        "authorization",
        "permission",
        "privacy_erasure",
        "block",
        "contact",
        "relationship_decision",
        "security",
        "data_integrity",
        "recovery",
    }
)


def evaluate_quarantine_request(
    *,
    criticality: TestCriticality,
    tags: frozenset[str],
    owner_team: str,
    requester_id: str,
    approver_id: str,
    expires_at: datetime | None,
    now: datetime,
    replacement_test_case_code: str | None = None,
) -> None:
    """Raise when a quarantine request violates governance policy."""

    if not owner_team.strip():
        raise RegressionPolicyError(
            "REGRESSION_QUARANTINE_OWNER_REQUIRED", "A quarantine request requires an owning team."
        )
    if expires_at is None or expires_at <= now:
        raise RegressionPolicyError(
            "REGRESSION_QUARANTINE_EXPIRY_REQUIRED",
            "A quarantine request requires a future expiry date.",
        )
    if approver_id == requester_id:
        raise RegressionPolicyError(
            "REGRESSION_QUARANTINE_SELF_APPROVAL",
            "A quarantine request cannot be approved by its requester.",
        )
    protected = bool(tags & NON_QUARANTINABLE_TAGS)
    if criticality in CRITICAL_CRITICALITIES or protected:
        if not replacement_test_case_code:
            raise RegressionPolicyError(
                "REGRESSION_CRITICAL_QUARANTINE_FORBIDDEN",
                "Critical or protected tests are repaired or retired behind an active "
                "replacement test; they are never ordinarily quarantined.",
            )


FLAKY_REPAIR_SLA_HOURS: dict[TestCriticality, int] = {
    TestCriticality.BLOCKER: 0,
    TestCriticality.CRITICAL: 24,
    TestCriticality.MAJOR: 72,
    TestCriticality.NORMAL: 336,
    TestCriticality.ADVISORY: 720,
}


def flaky_remediation_due_at(criticality: TestCriticality, detected_at: datetime) -> datetime:
    return detected_at + timedelta(hours=FLAKY_REPAIR_SLA_HOURS[criticality])


def pass_rate_excluding_quarantined(
    results: Mapping[str, RegressionTestResultStatus],
    quarantined_test_case_codes: Iterable[str],
) -> float:
    """Pass rate over non-quarantined tests only; empty eligible set fails closed."""

    quarantined = set(quarantined_test_case_codes)
    eligible = {code: status for code, status in results.items() if code not in quarantined}
    if not eligible:
        return 0.0
    passed = sum(1 for status in eligible.values() if status in PASSING_RESULT_STATUSES)
    return _ratio(passed, len(eligible))


@dataclass(frozen=True)
class QuarantineBudget:
    quarantined_count: int
    maximum_allowed: int
    open_critical_flaky: int
    hidden_retry_passes: int

    @property
    def blocked(self) -> bool:
        return (
            self.quarantined_count > self.maximum_allowed
            or self.open_critical_flaky > 0
            or self.hidden_retry_passes > 0
        )

    def reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if self.quarantined_count > self.maximum_allowed:
            reasons.append(
                f"quarantined tests {self.quarantined_count} exceed budget {self.maximum_allowed}"
            )
        if self.open_critical_flaky > 0:
            reasons.append(f"{self.open_critical_flaky} open critical flaky findings")
        if self.hidden_retry_passes > 0:
            reasons.append(
                f"{self.hidden_retry_passes} critical tests passed only after a diagnostic retry"
            )
        return tuple(reasons)


def resolve_first_attempt_result(
    attempts: Sequence[ExecutionRecord],
) -> RegressionTestResultStatus:
    """The first attempt decides the result; a later pass downgrades to unstable."""

    if not attempts:
        raise RegressionPolicyError(
            "REGRESSION_RESULT_MISSING", "A test result requires at least one execution attempt."
        )
    ordered = sorted(attempts, key=lambda item: item.attempt)
    first = ordered[0]
    if first.status in PASSING_RESULT_STATUSES:
        return RegressionTestResultStatus.PASSED
    if any(item.status in PASSING_RESULT_STATUSES for item in ordered[1:]):
        return RegressionTestResultStatus.FAILED_UNSTABLE
    return first.status


# ---------------------------------------------------------------------------
# 4. Contract testing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContractField:
    name: str
    data_type: str
    required: bool = False
    enum_values: frozenset[str] = frozenset()
    sensitive: bool = False
    classification: str | None = None


@dataclass(frozen=True)
class ContractSchema:
    contract_code: str
    version: str
    fields: tuple[ContractField, ...] = ()
    operations: frozenset[str] = frozenset()

    def field_map(self) -> dict[str, ContractField]:
        mapping: dict[str, ContractField] = {}
        for item in self.fields:
            if item.name in mapping:
                raise RegressionPolicyError(
                    "REGRESSION_CONTRACT_FIELD_DUPLICATE",
                    f"Contract {self.contract_code} declares field {item.name!r} twice.",
                )
            mapping[item.name] = item
        return mapping


@dataclass(frozen=True)
class ContractChange:
    kind: ContractChangeKind
    field_name: str
    detail: str
    breaking: bool


@dataclass(frozen=True)
class ContractComparison:
    contract_code: str
    previous_version: str
    next_version: str
    changes: tuple[ContractChange, ...]
    compatibility: ContractCompatibility

    @property
    def breaking_changes(self) -> tuple[ContractChange, ...]:
        return tuple(change for change in self.changes if change.breaking)

    @property
    def compatible(self) -> bool:
        return self.compatibility is not ContractCompatibility.BREAKING


def compare_contract_schemas(
    previous: ContractSchema, candidate: ContractSchema
) -> ContractComparison:
    """Decide provider/consumer compatibility between two contract versions.

    Additive optional fields stay compatible.  Removing a field, adding a
    required field, tightening an optional field into a required one, changing a
    data type, removing an enum value or removing an operation are breaking.
    A newly added sensitive field without a classification is breaking too,
    because downstream masking cannot be verified.
    """

    if previous.contract_code != candidate.contract_code:
        raise RegressionPolicyError(
            "REGRESSION_CONTRACT_CODE_MISMATCH",
            "Contract comparison requires the same contract code on both versions.",
        )
    before = previous.field_map()
    after = candidate.field_map()
    changes: list[ContractChange] = []

    for name in sorted(set(before) - set(after)):
        changes.append(
            ContractChange(
                kind=ContractChangeKind.FIELD_REMOVED,
                field_name=name,
                detail=f"Field {name!r} was removed.",
                breaking=True,
            )
        )
    for name in sorted(set(after) - set(before)):
        item = after[name]
        if item.required:
            changes.append(
                ContractChange(
                    kind=ContractChangeKind.FIELD_ADDED_REQUIRED,
                    field_name=name,
                    detail=f"Required field {name!r} was added.",
                    breaking=True,
                )
            )
        else:
            changes.append(
                ContractChange(
                    kind=ContractChangeKind.FIELD_ADDED_OPTIONAL,
                    field_name=name,
                    detail=f"Optional field {name!r} was added.",
                    breaking=False,
                )
            )
        if item.sensitive and not item.classification:
            changes.append(
                ContractChange(
                    kind=ContractChangeKind.SENSITIVE_FIELD_UNCLASSIFIED,
                    field_name=name,
                    detail=f"Sensitive field {name!r} was added without a classification.",
                    breaking=True,
                )
            )
    for name in sorted(set(before) & set(after)):
        old, new = before[name], after[name]
        if old.data_type != new.data_type:
            changes.append(
                ContractChange(
                    kind=ContractChangeKind.FIELD_TYPE_CHANGED,
                    field_name=name,
                    detail=f"Field {name!r} changed type {old.data_type} -> {new.data_type}.",
                    breaking=True,
                )
            )
        if not old.required and new.required:
            changes.append(
                ContractChange(
                    kind=ContractChangeKind.FIELD_MADE_REQUIRED,
                    field_name=name,
                    detail=f"Optional field {name!r} became required.",
                    breaking=True,
                )
            )
        if old.required and not new.required:
            changes.append(
                ContractChange(
                    kind=ContractChangeKind.FIELD_MADE_OPTIONAL,
                    field_name=name,
                    detail=f"Required field {name!r} became optional.",
                    breaking=False,
                )
            )
        for removed in sorted(old.enum_values - new.enum_values):
            changes.append(
                ContractChange(
                    kind=ContractChangeKind.ENUM_VALUE_REMOVED,
                    field_name=name,
                    detail=f"Enum value {removed!r} was removed from {name!r}.",
                    breaking=True,
                )
            )
        for added in sorted(new.enum_values - old.enum_values):
            changes.append(
                ContractChange(
                    kind=ContractChangeKind.ENUM_VALUE_ADDED,
                    field_name=name,
                    detail=f"Enum value {added!r} was added to {name!r}.",
                    breaking=False,
                )
            )
    for operation in sorted(previous.operations - candidate.operations):
        changes.append(
            ContractChange(
                kind=ContractChangeKind.OPERATION_REMOVED,
                field_name=operation,
                detail=f"Operation {operation!r} was removed.",
                breaking=True,
            )
        )

    if any(change.breaking for change in changes):
        compatibility = ContractCompatibility.BREAKING
    elif changes:
        compatibility = ContractCompatibility.ADDITIVE
    else:
        compatibility = ContractCompatibility.COMPATIBLE
    return ContractComparison(
        contract_code=previous.contract_code,
        previous_version=previous.version,
        next_version=candidate.version,
        changes=tuple(changes),
        compatibility=compatibility,
    )


@dataclass(frozen=True)
class ConsumerExpectation:
    consumer_code: str
    required_fields: frozenset[str] = frozenset()
    expected_types: dict[str, str] = field(default_factory=dict)
    authorized_classifications: frozenset[str] = frozenset()


def verify_consumer_contract(
    provider: ContractSchema, expectation: ConsumerExpectation
) -> tuple[str, ...]:
    """Verify a consumer-driven contract against the current provider schema."""

    provider_fields = provider.field_map()
    violations: list[str] = []
    for name in sorted(expectation.required_fields):
        item = provider_fields.get(name)
        if item is None:
            violations.append(
                f"{expectation.consumer_code} requires missing field {name!r} "
                f"from {provider.contract_code}"
            )
            continue
        if item.sensitive:
            classification = item.classification or "unclassified"
            if classification not in expectation.authorized_classifications:
                violations.append(
                    f"{expectation.consumer_code} is not authorized for sensitive field "
                    f"{name!r} classified {classification!r}"
                )
    for name, expected_type in sorted(expectation.expected_types.items()):
        item = provider_fields.get(name)
        if item is None:
            violations.append(
                f"{expectation.consumer_code} expects field {name!r} that the provider "
                "no longer publishes"
            )
        elif item.data_type != expected_type:
            violations.append(
                f"{expectation.consumer_code} expects {name!r} as {expected_type} but the "
                f"provider publishes {item.data_type}"
            )
    return tuple(violations)


def evaluate_contract_gate(
    comparisons: Sequence[ContractComparison],
    approved_breaking_contract_codes: frozenset[str] = frozenset(),
) -> tuple[bool, tuple[str, ...]]:
    """Block on any unapproved breaking contract change."""

    failures: list[str] = []
    for comparison in comparisons:
        if comparison.compatibility is not ContractCompatibility.BREAKING:
            continue
        if comparison.contract_code in approved_breaking_contract_codes:
            continue
        detail = "; ".join(change.detail for change in comparison.breaking_changes)
        failures.append(f"{comparison.contract_code}@{comparison.next_version}: {detail}")
    return (not failures, tuple(failures))
