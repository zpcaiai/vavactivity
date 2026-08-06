"""Declarative gate DSL and gate-run reproducibility."""

from __future__ import annotations

import pytest

from vav.modules.quality.domain import (
    ALLOWED_GATE_OPERATORS,
    QualityPolicyError,
    evaluate_gate_condition,
)


def test_allowed_operators_are_exactly_the_published_set() -> None:
    assert ALLOWED_GATE_OPERATORS == frozenset(
        {"eq", "neq", "gt", "gte", "lt", "lte", "contains", "all_passed", "none_open"}
    )


@pytest.mark.parametrize(
    ("operator", "expected", "observed", "result"),
    [
        ("eq", 1.0, 1.0, True),
        ("eq", 1.0, 0.99, False),
        ("neq", 0, 3, True),
        ("gt", 0.95, 0.96, True),
        ("gte", 0.95, 0.95, True),
        ("lt", 5, 4, True),
        ("lte", 5, 5, True),
        ("contains", "critical", ["critical", "high"], True),
        ("all_passed", True, ["passed", "passed"], True),
        ("all_passed", True, ["passed", "failed"], False),
        ("all_passed", True, [], False),
        ("none_open", True, [], True),
        ("none_open", True, ["open"], False),
    ],
)
def test_operator_semantics(operator: str, expected: object, observed: object, result: bool) -> None:
    condition = {
        "metric": "blocker_requirement_trace_coverage",
        "operator": operator,
        "expected": expected,
    }
    assert evaluate_gate_condition(condition, observed) is result


def test_condition_must_be_closed() -> None:
    with pytest.raises(QualityPolicyError) as error:
        evaluate_gate_condition(
            {
                "metric": "critical_test_pass_rate",
                "operator": "eq",
                "expected": 1.0,
                "extra": "sneaky",
            },
            1.0,
        )
    assert error.value.code == "QUALITY_GATE_CONDITION_INVALID"


def test_missing_key_is_rejected() -> None:
    with pytest.raises(QualityPolicyError):
        evaluate_gate_condition({"metric": "x_metric", "operator": "eq"}, 1.0)


@pytest.mark.parametrize(
    "operator",
    ["exec", "eval", "python", "sql", "shell", "__import__", "regex", "custom"],
)
def test_arbitrary_operators_are_rejected(operator: str) -> None:
    with pytest.raises(QualityPolicyError) as error:
        evaluate_gate_condition(
            {"metric": "critical_test_pass_rate", "operator": operator, "expected": 1.0},
            1.0,
        )
    assert error.value.code == "QUALITY_GATE_OPERATOR_INVALID"


@pytest.mark.parametrize(
    "metric",
    ["", "X", "1metric", "metric-with-dash", "os.system('rm -rf /')", "SELECT 1"],
)
def test_metric_names_are_restricted(metric: str) -> None:
    with pytest.raises(QualityPolicyError) as error:
        evaluate_gate_condition({"metric": metric, "operator": "eq", "expected": 1.0}, 1.0)
    assert error.value.code == "QUALITY_GATE_METRIC_INVALID"


def test_incomparable_value_fails_closed_with_policy_error() -> None:
    with pytest.raises(QualityPolicyError) as error:
        evaluate_gate_condition(
            {"metric": "critical_dead_letters", "operator": "gt", "expected": 1}, "many"
        )
    assert error.value.code == "QUALITY_GATE_VALUE_INVALID"


def test_gate_results_are_reproducible() -> None:
    condition = {"metric": "critical_journey_e2e_pass_rate", "operator": "eq", "expected": 1.0}
    results = {evaluate_gate_condition(condition, 1.0) for _ in range(20)}
    assert results == {True}
