"""Partner-preference validation.

Only criteria that business, privacy and legal review approved may enter
automated filtering. Hard constraints are always explicit, are never relaxed
without the member's own permission, and are never inferred from free text.
"""

# ruff: noqa: E501

from __future__ import annotations

from typing import Any

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.matchmaking_profiles.domain import (
    PreferenceImportance,
    PreferenceOperator,
)
from vav.modules.matchmaking_profiles.taxonomies import (
    APPROVED_PREFERENCE_CRITERIA,
    taxonomy_value_codes,
)

_TAXONOMY_FOR_CRITERION: dict[str, str] = {
    "relocation_willingness": "relocation_willingness",
    "faith_status_code": "faith_status",
    "church_tradition_codes": "church_tradition",
    "marital_status_code": "marital_status",
    "open_to_partner_with_children": "open_to_partner_with_children",
    "desire_children_code": "desire_children",
    "education_level_code": "education_level",
    "daily_schedule_code": "daily_schedule",
    "smoking_status_code": "smoking_status",
    "alcohol_use_code": "alcohol_use",
    "leisure_interest_codes": "leisure_interest",
    "communication_preference_codes": "communication_preference",
}

_LIST_OPERATORS = frozenset({"in", "contains_any", "contains_all"})


def _invalid(message: str, criterion_code: str) -> VavError:
    return VavError(
        "DATING_PREFERENCE_INVALID",
        message,
        status_code=422,
        details=[{"criterion_code": criterion_code}],
    )


def validate_criterion(criterion: dict[str, Any]) -> dict[str, Any]:
    """Validate one criterion and return its normalised form."""
    settings = get_settings()
    code = str(criterion.get("criterion_code", ""))
    definition = APPROVED_PREFERENCE_CRITERIA.get(code)
    if definition is None:
        raise _invalid(
            "This criterion is not approved for automated matching.",
            code,
        )

    operator = str(criterion.get("operator", ""))
    if operator not in definition["operators"]:
        raise _invalid(
            f"Operator '{operator}' cannot be used with '{code}'.",
            code,
        )
    try:
        PreferenceOperator(operator)
    except ValueError as exc:
        raise _invalid(f"Unknown operator '{operator}'.", code) from exc

    importance = str(criterion.get("importance", ""))
    try:
        parsed_importance = PreferenceImportance(importance)
    except ValueError as exc:
        raise _invalid(f"Unknown importance '{importance}'.", code) from exc

    hard_constraint = bool(criterion.get("hard_constraint", False))
    if hard_constraint and not settings.dating_allow_hard_constraints:
        raise _invalid("Hard constraints are currently disabled.", code)
    # Importance and exclusion strength must agree so the member always knows
    # which criteria actually exclude people.
    if hard_constraint and parsed_importance != PreferenceImportance.REQUIRED:
        raise _invalid(
            "A hard constraint must be marked as 'required' so its exclusion effect is explicit.",
            code,
        )
    if parsed_importance == PreferenceImportance.NO_PREFERENCE and hard_constraint:
        raise _invalid("A criterion with no preference cannot exclude anyone.", code)

    value = criterion.get("desired_value")
    normalised_value = _validate_value(code, operator, value)

    allow_relaxation = bool(criterion.get("allow_system_relaxation", False))
    if hard_constraint and allow_relaxation is False:
        allow_relaxation = False
    if allow_relaxation and not criterion.get("relaxation_acknowledged", False) and hard_constraint:
        raise _invalid(
            "Relaxing a hard constraint requires explicit acknowledgement.",
            code,
        )

    return {
        "criterion_code": code,
        "operator": operator,
        "desired_value": normalised_value,
        "importance": parsed_importance.value,
        "hard_constraint": hard_constraint,
        "allow_unknown": bool(criterion.get("allow_unknown", True)),
        "allow_system_relaxation": allow_relaxation,
        "user_explanation": criterion.get("user_explanation"),
    }


def _validate_value(code: str, operator: str, value: Any) -> Any:
    if operator == "range":
        if not isinstance(value, dict) or "minimum" not in value or "maximum" not in value:
            raise _invalid("A range criterion requires 'minimum' and 'maximum'.", code)
        minimum = value["minimum"]
        maximum = value["maximum"]
        if not isinstance(minimum, int) or not isinstance(maximum, int):
            raise _invalid("Range bounds must be whole numbers.", code)
        if minimum > maximum:
            raise _invalid("The range minimum cannot be greater than the maximum.", code)
        if code == "age_range":
            floor = get_settings().dating_minimum_age
            if minimum < floor:
                raise _invalid(
                    f"The age range cannot start below the platform minimum of {floor}.", code
                )
            if maximum > 120:
                raise _invalid("The age range maximum is not realistic.", code)
        return {"minimum": minimum, "maximum": maximum}

    if operator == "boolean":
        if not isinstance(value, bool):
            raise _invalid("A boolean criterion requires true or false.", code)
        return value

    if operator in {"at_least", "at_most"}:
        if not isinstance(value, int | str):
            raise _invalid("This criterion requires a single comparable value.", code)
        return value

    if operator in _LIST_OPERATORS:
        if not isinstance(value, list) or not value:
            raise _invalid("This criterion requires a non-empty list of values.", code)
        if len(value) != len(set(map(str, value))):
            raise _invalid("Duplicate values are not allowed.", code)
        _validate_taxonomy_values(code, [str(item) for item in value])
        return [str(item) for item in value]

    if operator == "equals":
        if isinstance(value, list | dict):
            raise _invalid("An equality criterion requires a single value.", code)
        _validate_taxonomy_values(code, [str(value)])
        return value

    raise _invalid(f"Unsupported operator '{operator}'.", code)


def _validate_taxonomy_values(code: str, values: list[str]) -> None:
    taxonomy = _TAXONOMY_FOR_CRITERION.get(code)
    if taxonomy is None:
        return
    allowed = taxonomy_value_codes(taxonomy)
    unknown = [value for value in values if value not in allowed]
    if unknown:
        raise _invalid(
            f"These values are not part of the active '{taxonomy}' taxonomy: {', '.join(sorted(unknown))}.",
            code,
        )


def validate_criteria(criteria: list[dict[str, Any]]) -> list[dict[str, Any]]:
    settings = get_settings()
    if len(criteria) > settings.dating_preferences_max_criteria:
        raise VavError(
            "DATING_PREFERENCE_LIMIT_EXCEEDED",
            f"A member may configure at most {settings.dating_preferences_max_criteria} criteria.",
            status_code=422,
        )
    seen: set[str] = set()
    normalised: list[dict[str, Any]] = []
    for criterion in criteria:
        result = validate_criterion(criterion)
        if result["criterion_code"] in seen:
            raise _invalid("This criterion was provided more than once.", result["criterion_code"])
        seen.add(result["criterion_code"])
        normalised.append(result)
    _check_contradictions(normalised)
    return normalised


def _check_contradictions(criteria: list[dict[str, Any]]) -> None:
    by_code = {criterion["criterion_code"]: criterion for criterion in criteria}
    children = by_code.get("has_children")
    open_to = by_code.get("open_to_partner_with_children")
    if (
        children is not None
        and open_to is not None
        and children["hard_constraint"]
        and children["desired_value"] is True
        and open_to["hard_constraint"]
        and set(open_to["desired_value"]) == {"prefer_not"}
    ):
        raise VavError(
            "DATING_PREFERENCE_CONTRADICTION",
            "You required a partner who has children while also excluding partners with children.",
            status_code=422,
            details=[{"criterion_codes": ["has_children", "open_to_partner_with_children"]}],
        )


def hard_constraint_summary(criteria: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The member-facing list of criteria that actually exclude candidates."""
    return [
        {
            "criterion_code": criterion["criterion_code"],
            "operator": criterion["operator"],
            "excludes_unknown_values": not criterion["allow_unknown"],
            "may_be_relaxed_by_system": criterion["allow_system_relaxation"],
        }
        for criterion in criteria
        if criterion["hard_constraint"]
    ]
