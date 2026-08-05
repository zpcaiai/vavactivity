"""Bidirectional hard-constraint engine.

A pair passes only when both directions pass. Only criteria a member marked as
hard, plus approved platform eligibility rules, can exclude a candidate; a
missing value follows the member's own unknown policy and is never silently
treated as a failure.
"""

# ruff: noqa: E501

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from vav.modules.recommendations.domain import (
    NON_RELAXABLE_CRITERIA,
    SUPPORTED_HARD_CONSTRAINTS,
)
from vav.modules.recommendations.features import extract_value

HARD_CONSTRAINT_POLICY_VERSION = "1.0.0"

Direction = Literal["viewer_to_candidate", "candidate_to_viewer"]


@dataclass(frozen=True)
class ConstraintResult:
    criterion_code: str
    direction: Direction
    #: ``None`` means the candidate value is unknown.
    passed: bool | None
    reason_code: str
    source_preference_version: int
    evaluated_value_snapshot: dict[str, Any] = field(default_factory=dict)
    unknown_policy: str | None = None
    relaxed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "criterion_code": self.criterion_code,
            "direction": self.direction,
            "passed": self.passed,
            "reason_code": self.reason_code,
            "source_preference_version": self.source_preference_version,
            "evaluated_value_snapshot": self.evaluated_value_snapshot,
            "unknown_policy": self.unknown_policy,
            "relaxed": self.relaxed,
        }


@dataclass(frozen=True)
class HardConstraintEvaluation:
    passed: bool
    viewer_constraints: list[ConstraintResult]
    candidate_constraints: list[ConstraintResult]
    blocking_codes: list[str]
    unknown_codes: list[str]
    relaxed_codes: list[str]
    policy_version: str = HARD_CONSTRAINT_POLICY_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "viewer_constraints": [item.as_dict() for item in self.viewer_constraints],
            "candidate_constraints": [item.as_dict() for item in self.candidate_constraints],
            "blocking_codes": self.blocking_codes,
            "unknown_codes": self.unknown_codes,
            "relaxed_codes": self.relaxed_codes,
            "policy_version": self.policy_version,
        }


# --------------------------------------------------------------------------
# Operator evaluation
# --------------------------------------------------------------------------


def _as_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, list | tuple | set):
        return {str(item) for item in value}
    return {str(value)}


def _as_number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def evaluate_operator(operator: str, desired: Any, actual: Any) -> bool | None:
    """Return ``True``/``False``, or ``None`` when the candidate value is unknown."""
    if actual is None:
        return None
    if operator == "equals":
        if isinstance(actual, list | tuple | set):
            return str(desired) in _as_set(actual)
        return str(desired) == str(actual)
    if operator == "in":
        wanted = _as_set(desired)
        if isinstance(actual, list | tuple | set):
            return bool(wanted & _as_set(actual))
        return str(actual) in wanted
    if operator == "contains_any":
        return bool(_as_set(desired) & _as_set(actual))
    if operator == "contains_all":
        return _as_set(desired).issubset(_as_set(actual))
    if operator == "boolean":
        expected = bool(desired.get("value", True)) if isinstance(desired, dict) else bool(desired)
        return bool(actual) is expected
    if operator in {"range", "at_least", "at_most"}:
        value = _as_number(actual)
        if value is None:
            return None
        if operator == "range":
            bounds = _bounds(desired)
            if bounds is None:
                return None
            minimum, maximum = bounds
            return minimum <= value <= maximum
        threshold = _as_number(
            desired.get("value") if isinstance(desired, dict) else desired,
        )
        if threshold is None:
            return None
        return value >= threshold if operator == "at_least" else value <= threshold
    raise ValueError(f"unsupported preference operator {operator}")


def _bounds(desired: Any) -> tuple[float, float] | None:
    if isinstance(desired, dict):
        minimum = _as_number(desired.get("min", desired.get("minimum")))
        maximum = _as_number(desired.get("max", desired.get("maximum")))
    elif isinstance(desired, list | tuple) and len(desired) == 2:
        minimum = _as_number(desired[0])
        maximum = _as_number(desired[1])
    else:
        return None
    if minimum is None or maximum is None:
        return None
    return minimum, maximum


# --------------------------------------------------------------------------
# Platform rules
# --------------------------------------------------------------------------


def relationship_eligibility(
    source: dict[str, Any], target: dict[str, Any]
) -> tuple[bool | None, str]:
    """Check that the source member's stated partner genders include the target."""
    accepted = source.get("eligible_partner_gender_codes") or []
    target_gender = target.get("gender_code")
    if not accepted or target_gender is None:
        return None, "relationship_eligibility_unknown"
    if str(target_gender) in {str(item) for item in accepted}:
        return True, "relationship_eligibility_satisfied"
    return False, "relationship_eligibility_mismatch"


def adult_eligibility(projection: dict[str, Any], minimum_age: int) -> tuple[bool | None, str]:
    age = projection.get("age_years")
    if age is None:
        return None, "age_unknown"
    return (int(age) >= minimum_age, "adult_eligibility")


# --------------------------------------------------------------------------
# Directional evaluation
# --------------------------------------------------------------------------


def evaluate_direction(
    *,
    criteria: list[dict[str, Any]],
    source_projection: dict[str, Any],
    target_projection: dict[str, Any],
    direction: Direction,
    preference_version: int,
    minimum_age: int,
    allow_relaxation: bool,
    unknown_value_policy: str,
) -> list[ConstraintResult]:
    """Evaluate one member's hard rules against the other member's projection."""
    results: list[ConstraintResult] = []

    passed, reason = adult_eligibility(target_projection, minimum_age)
    results.append(
        ConstraintResult(
            criterion_code="adult_eligibility",
            direction=direction,
            passed=passed if passed is not None else False,
            reason_code=reason if passed is not False else "below_minimum_age",
            source_preference_version=preference_version,
            evaluated_value_snapshot={"minimum_age": minimum_age},
        )
    )

    eligible, eligibility_reason = relationship_eligibility(source_projection, target_projection)
    results.append(
        ConstraintResult(
            criterion_code="relationship_eligibility",
            direction=direction,
            passed=eligible if eligible is not None else False,
            reason_code=eligibility_reason,
            source_preference_version=preference_version,
            evaluated_value_snapshot={},
        )
    )

    for criterion in criteria:
        if not criterion.get("hard_constraint"):
            continue
        code = str(criterion["criterion_code"])
        if code not in SUPPORTED_HARD_CONSTRAINTS:
            continue
        operator = str(criterion["operator"])
        desired = criterion.get("desired_value")
        actual = extract_value(target_projection, code)
        outcome = evaluate_operator(operator, desired, actual)

        allow_unknown = bool(criterion.get("allow_unknown", True))
        snapshot: dict[str, Any] = {
            "operator": operator,
            "candidate_value_known": actual is not None,
        }

        if outcome is None:
            resolved = allow_unknown
            results.append(
                ConstraintResult(
                    criterion_code=code,
                    direction=direction,
                    passed=resolved,
                    reason_code=("unknown_allowed" if allow_unknown else "unknown_not_allowed"),
                    source_preference_version=preference_version,
                    evaluated_value_snapshot=snapshot,
                    unknown_policy=("allow_unknown" if allow_unknown else unknown_value_policy),
                )
            )
            continue

        if outcome:
            results.append(
                ConstraintResult(
                    criterion_code=code,
                    direction=direction,
                    passed=True,
                    reason_code="satisfied",
                    source_preference_version=preference_version,
                    evaluated_value_snapshot=snapshot,
                )
            )
            continue

        relaxable = (
            allow_relaxation
            and bool(criterion.get("allow_system_relaxation"))
            and code not in NON_RELAXABLE_CRITERIA
        )
        results.append(
            ConstraintResult(
                criterion_code=code,
                direction=direction,
                passed=bool(relaxable),
                reason_code=("relaxed_with_member_permission" if relaxable else "not_satisfied"),
                source_preference_version=preference_version,
                evaluated_value_snapshot=snapshot,
                relaxed=relaxable,
            )
        )

    return results


def evaluate_pair(
    *,
    viewer_projection: dict[str, Any],
    candidate_projection: dict[str, Any],
    viewer_criteria: list[dict[str, Any]],
    candidate_criteria: list[dict[str, Any]],
    viewer_preference_version: int,
    candidate_preference_version: int,
    minimum_age: int,
    allow_viewer_relaxation: bool = False,
    allow_candidate_relaxation: bool = False,
    unknown_value_policy: str = "lower_confidence",
) -> HardConstraintEvaluation:
    """Evaluate both directions; the pair passes only when both do."""
    viewer_results = evaluate_direction(
        criteria=viewer_criteria,
        source_projection=viewer_projection,
        target_projection=candidate_projection,
        direction="viewer_to_candidate",
        preference_version=viewer_preference_version,
        minimum_age=minimum_age,
        allow_relaxation=allow_viewer_relaxation,
        unknown_value_policy=unknown_value_policy,
    )
    candidate_results = evaluate_direction(
        criteria=candidate_criteria,
        source_projection=candidate_projection,
        target_projection=viewer_projection,
        direction="candidate_to_viewer",
        preference_version=candidate_preference_version,
        minimum_age=minimum_age,
        allow_relaxation=allow_candidate_relaxation,
        unknown_value_policy=unknown_value_policy,
    )

    blocking: list[str] = []
    unknown: list[str] = []
    relaxed: list[str] = []
    for result in (*viewer_results, *candidate_results):
        if result.passed is False:
            blocking.append(f"{result.direction}:{result.criterion_code}")
        if result.unknown_policy is not None or result.reason_code.startswith("unknown"):
            unknown.append(f"{result.direction}:{result.criterion_code}")
        if result.relaxed:
            relaxed.append(f"{result.direction}:{result.criterion_code}")

    return HardConstraintEvaluation(
        passed=not blocking,
        viewer_constraints=viewer_results,
        candidate_constraints=candidate_results,
        blocking_codes=sorted(set(blocking)),
        unknown_codes=sorted(set(unknown)),
        relaxed_codes=sorted(set(relaxed)),
    )


def aggregate_failure_reasons(evaluations: list[HardConstraintEvaluation]) -> dict[str, int]:
    """Aggregate blocking criteria for diagnostics.

    Only criterion codes and counts are produced: a member never learns which
    individual account rejected them, and operators see statistics only.
    """
    counts: dict[str, int] = {}
    for evaluation in evaluations:
        for code in evaluation.blocking_codes:
            criterion = code.split(":", 1)[1]
            counts[criterion] = counts.get(criterion, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))
