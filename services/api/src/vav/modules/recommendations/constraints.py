"""Bidirectional hard-constraint evaluation.

A pair is only eligible when A's hard constraints accept B *and* B's hard
constraints accept A. A candidate who simply left a field blank is never
treated as failing: the member's own ``allow_unknown`` setting decides.
"""

# ruff: noqa: E501

from __future__ import annotations

from typing import Any

from vav.modules.recommendations.domain import NEVER_RELAXABLE_CONSTRAINTS
from vav.modules.recommendations.strategy import (
    HARD_CONSTRAINT_CRITERIA,
    HARD_CONSTRAINT_POLICY_VERSION,
)

VIEWER_TO_CANDIDATE = "viewer_to_candidate"
CANDIDATE_TO_VIEWER = "candidate_to_viewer"


def _projection_value(projection: dict[str, Any], criterion_code: str) -> Any:
    """Read the normalised value a criterion compares against."""
    direct = {
        "age_range": projection.get("age_years"),
        "country_code": projection.get("country_code"),
        "region_code": projection.get("region_code"),
        "city_code": projection.get("city_code"),
        "relocation_willingness": projection.get("relocation_willingness"),
        "language_codes": projection.get("language_codes"),
        "marital_status_code": projection.get("marital_status_code"),
        "relationship_intent": projection.get("relationship_intent"),
    }
    if criterion_code in direct:
        return direct[criterion_code]

    faith_codes = list(projection.get("faith_codes") or [])
    lifestyle_codes = list(projection.get("lifestyle_codes") or [])
    if criterion_code == "faith_status_code":
        return next(
            (code for code in faith_codes if not code.startswith("marriage_faith_importance:")),
            None,
        )
    if criterion_code == "church_tradition_codes":
        return faith_codes
    if criterion_code == "marriage_faith_importance":
        for code in faith_codes:
            if code.startswith("marriage_faith_importance:"):
                return int(code.split(":", 1)[1])
        return None
    if criterion_code == "has_children":
        children = projection.get("children_status_code")
        if children is None:
            return None
        return children != "no_children"
    if criterion_code == "open_to_partner_with_children":
        return projection.get("children_status_code")
    for prefix, code in (
        ("desire_children_code:", "desire_children_code"),
        ("smoking_status_code:", "smoking_status_code"),
        ("daily_schedule_code:", "daily_schedule_code"),
        ("education_level_code:", "education_level_code"),
    ):
        if criterion_code == code:
            for value in lifestyle_codes:
                if value.startswith(prefix):
                    return value.split(":", 1)[1]
            return None
    return None


def _compare(operator: str, desired: Any, actual: Any) -> bool:
    if operator == "equals":
        return bool(actual == desired)
    if operator == "in":
        return actual in set(desired)
    if operator == "range":
        return bool(int(desired["minimum"]) <= int(actual) <= int(desired["maximum"]))
    if operator == "at_least":
        return bool(actual >= desired)
    if operator == "at_most":
        return bool(actual <= desired)
    if operator == "contains_any":
        return bool(set(_as_list(actual)) & set(desired))
    if operator == "contains_all":
        return set(desired) <= set(_as_list(actual))
    if operator == "boolean":
        return bool(actual) is bool(desired)
    return False


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def relationship_eligibility(
    viewer_projection: dict[str, Any], candidate_projection: dict[str, Any]
) -> tuple[bool, str | None]:
    """Both members must accept the other's gender; never widened by the system."""
    viewer_gender = viewer_projection.get("gender_code")
    candidate_gender = candidate_projection.get("gender_code")
    viewer_accepts = set(viewer_projection.get("eligible_partner_gender_codes") or [])
    candidate_accepts = set(candidate_projection.get("eligible_partner_gender_codes") or [])
    if not viewer_gender or not candidate_gender or not viewer_accepts or not candidate_accepts:
        return False, "relationship_eligibility_unknown"
    if candidate_gender not in viewer_accepts:
        return False, "viewer_does_not_accept_candidate"
    if viewer_gender not in candidate_accepts:
        return False, "candidate_does_not_accept_viewer"
    return True, None


def evaluate_direction(
    *,
    criteria: list[dict[str, Any]],
    target_projection: dict[str, Any],
    direction: str,
    source_preference_version: int,
    allow_relaxation: bool,
    relaxable_criteria: frozenset[str],
) -> list[dict[str, Any]]:
    """Evaluate one member's hard constraints against the other's projection."""
    results: list[dict[str, Any]] = []
    for criterion in criteria:
        if not criterion.get("hard_constraint"):
            continue
        code = str(criterion["criterion_code"])
        if code not in HARD_CONSTRAINT_CRITERIA:
            # Only approved criteria may exclude anyone.
            results.append(
                {
                    "criterion_code": code,
                    "direction": direction,
                    "passed": None,
                    "reason_code": "criterion_not_approved_for_hard_filtering",
                    "source_preference_version": source_preference_version,
                    "evaluated_value_snapshot": {},
                    "unknown_policy": None,
                }
            )
            continue

        actual = _projection_value(target_projection, code)
        if actual is None or actual == []:
            allow_unknown = bool(criterion.get("allow_unknown", True))
            results.append(
                {
                    "criterion_code": code,
                    "direction": direction,
                    # A blank field is "unknown", never an automatic failure.
                    "passed": bool(allow_unknown),
                    "reason_code": "unknown_allowed" if allow_unknown else "unknown_not_accepted",
                    "source_preference_version": source_preference_version,
                    "evaluated_value_snapshot": {"value_present": False},
                    "unknown_policy": "allow" if allow_unknown else "exclude",
                }
            )
            continue

        try:
            passed = _compare(str(criterion["operator"]), criterion["desired_value"], actual)
        except (TypeError, ValueError, KeyError):
            passed = False

        relaxed = False
        if (
            not passed
            and allow_relaxation
            and bool(criterion.get("allow_system_relaxation"))
            and code in relaxable_criteria
            and code not in NEVER_RELAXABLE_CONSTRAINTS
        ):
            passed = True
            relaxed = True

        results.append(
            {
                "criterion_code": code,
                "direction": direction,
                "passed": passed,
                "reason_code": (
                    "relaxed_with_member_consent"
                    if relaxed
                    else ("matched" if passed else "did_not_match")
                ),
                "source_preference_version": source_preference_version,
                # Only the outcome is snapshotted; the other member's value is not.
                "evaluated_value_snapshot": {"value_present": True, "relaxed": relaxed},
                "unknown_policy": None,
            }
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
    viewer_allows_relaxation: bool = False,
    relaxable_criteria: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Full bidirectional hard-constraint evaluation for one candidate pair."""
    relaxable = relaxable_criteria or frozenset(
        {"country_code", "region_code", "city_code", "relocation_willingness"}
    )
    eligible, eligibility_reason = relationship_eligibility(viewer_projection, candidate_projection)

    viewer_results = evaluate_direction(
        criteria=viewer_criteria,
        target_projection=candidate_projection,
        direction=VIEWER_TO_CANDIDATE,
        source_preference_version=viewer_preference_version,
        allow_relaxation=viewer_allows_relaxation,
        relaxable_criteria=relaxable,
    )
    candidate_results = evaluate_direction(
        criteria=candidate_criteria,
        target_projection=viewer_projection,
        direction=CANDIDATE_TO_VIEWER,
        source_preference_version=candidate_preference_version,
        # The other member's constraints are never relaxed on the viewer's behalf.
        allow_relaxation=False,
        relaxable_criteria=frozenset(),
    )

    blocking: list[str] = []
    unknown: list[str] = []
    relaxations: list[str] = []
    if not eligible:
        blocking.append("relationship_eligibility")
    for result in viewer_results + candidate_results:
        if result["passed"] is False:
            blocking.append(result["criterion_code"])
        if result["reason_code"] in {"unknown_allowed", "unknown_not_accepted"}:
            unknown.append(result["criterion_code"])
        if result["reason_code"] == "relaxed_with_member_consent":
            relaxations.append(result["criterion_code"])

    return {
        "passed": not blocking,
        "viewer_constraints": viewer_results,
        "candidate_constraints": candidate_results,
        "blocking_codes": sorted(set(blocking)),
        "unknown_codes": sorted(set(unknown)),
        "relaxations_applied": sorted(set(relaxations)),
        "relationship_eligibility_reason": eligibility_reason,
        "policy_version": HARD_CONSTRAINT_POLICY_VERSION,
    }


def diagnostic_summary(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate why candidates were excluded, without naming anyone.

    A member may learn that their faith requirement is narrowing the pool; they
    may never learn which specific person was excluded, or by which of that
    person's private criteria.
    """
    counts: dict[str, int] = {}
    unknown_counts: dict[str, int] = {}
    passed = 0
    for evaluation in evaluations:
        if evaluation["passed"]:
            passed += 1
            continue
        for code in evaluation["blocking_codes"]:
            counts[code] = counts.get(code, 0) + 1
        for code in evaluation["unknown_codes"]:
            unknown_counts[code] = unknown_counts.get(code, 0) + 1
    total = len(evaluations)
    return {
        "evaluated_pairs": total,
        "passed_pairs": passed,
        "pass_rate_bps": round(passed * 10000 / total) if total else 0,
        "blocking_criteria": dict(sorted(counts.items(), key=lambda item: -item[1])),
        "unknown_information_criteria": dict(
            sorted(unknown_counts.items(), key=lambda item: -item[1])
        ),
        "aggregate_only": True,
    }
