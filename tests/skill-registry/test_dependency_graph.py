from __future__ import annotations

import pytest

from vav_skill_runtime.dependencies import (
    DependencyConflict,
    DependencyGraph,
    DependencyRequirement,
)


def test_topological_order_and_cycle_evidence() -> None:
    graph = DependencyGraph()
    graph.add(DependencyRequirement("a", "b", ">=1.0.0 <2.0.0"))
    graph.add(DependencyRequirement("b", "c", ">=1.0.0 <2.0.0"))
    assert graph.topological_order("a") == ("c", "b", "a")
    graph.add(DependencyRequirement("c", "a", ">=1.0.0 <2.0.0"))
    with pytest.raises(DependencyConflict) as error:
        graph.topological_order("a")
    assert error.value.path == ("a", "b", "c", "a")


def test_missing_and_conflicting_dependencies_fail_with_path() -> None:
    graph = DependencyGraph()
    graph.add(DependencyRequirement("skill-a", "runtime", ">=1.0.0 <2.0.0"))
    graph.add(DependencyRequirement("skill-b", "runtime", ">=2.0.0 <3.0.0"))
    with pytest.raises(DependencyConflict, match="violates") as error:
        graph.validate_resolution({"runtime": "1.5.0"})
    assert error.value.path == ("skill-b", "runtime", "1.5.0")

    missing = DependencyGraph()
    missing.add(DependencyRequirement("skill-a", "provider-x", ">=1.0.0"))
    with pytest.raises(DependencyConflict, match="unresolved"):
        missing.validate_resolution({})
