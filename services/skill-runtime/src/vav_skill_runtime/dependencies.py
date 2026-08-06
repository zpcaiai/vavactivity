"""Dependency closure, cycle detection, and version-conflict evidence."""

from __future__ import annotations

from dataclasses import dataclass

from vav_skill_runtime.versions import satisfies


@dataclass(frozen=True)
class DependencyRequirement:
    source: str
    target: str
    constraint: str
    optional: bool = False
    peer: bool = False


class DependencyConflict(ValueError):
    def __init__(self, message: str, *, path: tuple[str, ...]) -> None:
        super().__init__(message)
        self.path = path


class DependencyGraph:
    def __init__(self) -> None:
        self._requirements: dict[str, list[DependencyRequirement]] = {}

    def add(self, requirement: DependencyRequirement) -> None:
        self._requirements.setdefault(requirement.source, []).append(requirement)

    def topological_order(self, root: str) -> tuple[str, ...]:
        visiting: list[str] = []
        visited: set[str] = set()
        ordered: list[str] = []

        def visit(node: str) -> None:
            if node in visiting:
                start = visiting.index(node)
                cycle = tuple(visiting[start:] + [node])
                raise DependencyConflict("cyclic Skill dependency", path=cycle)
            if node in visited:
                return
            visiting.append(node)
            for requirement in sorted(
                self._requirements.get(node, []), key=lambda item: item.target
            ):
                if not requirement.optional and not requirement.peer:
                    visit(requirement.target)
            visiting.pop()
            visited.add(node)
            ordered.append(node)

        visit(root)
        return tuple(ordered)

    def validate_resolution(self, resolved_versions: dict[str, str]) -> None:
        constraints: dict[str, list[DependencyRequirement]] = {}
        for requirements in self._requirements.values():
            for requirement in requirements:
                constraints.setdefault(requirement.target, []).append(requirement)
        for target, requirements in constraints.items():
            resolved = resolved_versions.get(target)
            required = [item for item in requirements if not item.optional]
            if resolved is None and required:
                raise DependencyConflict(
                    f"required dependency is unresolved: {target}",
                    path=(required[0].source, target),
                )
            if resolved is None:
                continue
            failing = [item for item in requirements if not satisfies(resolved, item.constraint)]
            if failing:
                evidence = tuple(item.source for item in failing) + (target, resolved)
                raise DependencyConflict(
                    f"{target}@{resolved} violates {[item.constraint for item in failing]}",
                    path=evidence,
                )
