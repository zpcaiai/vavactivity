"""Fail-closed JSON Schema compatibility analysis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

SENSITIVE_KEYS = (
    "x-vav-sensitive",
    "x-vav-classification",
    "x-vav-purpose",
    "x-vav-log-policy",
    "x-vav-export-policy",
)


@dataclass(frozen=True)
class ContractChange:
    path: str
    kind: str
    severity: Literal["compatible", "breaking", "review_required"]
    detail: str


@dataclass(frozen=True)
class ContractDiff:
    changes: tuple[ContractChange, ...]

    @property
    def breaking(self) -> bool:
        return any(change.severity == "breaking" for change in self.changes)

    @property
    def review_required(self) -> bool:
        return any(change.severity == "review_required" for change in self.changes)

    def require_version(self) -> Literal["major", "minor", "patch"]:
        if self.breaking:
            return "major"
        if self.changes:
            return "minor"
        return "patch"


def _types(schema: dict[str, Any]) -> frozenset[str]:
    value = schema.get("type")
    if isinstance(value, str):
        return frozenset({value})
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return frozenset(value)
    return frozenset()


def compare_schemas(old: dict[str, Any], new: dict[str, Any]) -> ContractDiff:
    """Compare producer/consumer schemas and flag changes requiring a major release."""

    changes: list[ContractChange] = []

    def visit(before: dict[str, Any], after: dict[str, Any], path: str) -> None:
        before_types = _types(before)
        after_types = _types(after)
        if before_types and after_types and not before_types.issubset(after_types):
            changes.append(
                ContractChange(path, "type_narrowed", "breaking", "accepted types were removed")
            )
        before_enum = before.get("enum")
        after_enum = after.get("enum")
        if isinstance(before_enum, list) and isinstance(after_enum, list):
            if not set(before_enum).issubset(set(after_enum)):
                changes.append(
                    ContractChange(path, "enum_narrowed", "breaking", "enum values were removed")
                )
        for key in SENSITIVE_KEYS:
            if before.get(key) != after.get(key):
                changes.append(
                    ContractChange(
                        path,
                        "data_policy_changed",
                        "review_required",
                        f"{key} changed and requires privacy/security review",
                    )
                )

        before_properties = before.get("properties", {})
        after_properties = after.get("properties", {})
        if isinstance(before_properties, dict) and isinstance(after_properties, dict):
            before_required = set(before.get("required", []))
            after_required = set(after.get("required", []))
            for name in sorted(before_properties.keys() - after_properties.keys()):
                changes.append(
                    ContractChange(
                        f"{path}/{name}", "property_removed", "breaking", "field removed"
                    )
                )
            for name in sorted(after_properties.keys() - before_properties.keys()):
                severity: Literal["compatible", "breaking"] = (
                    "breaking" if name in after_required else "compatible"
                )
                changes.append(
                    ContractChange(
                        f"{path}/{name}",
                        "property_added",
                        severity,
                        "required field added"
                        if severity == "breaking"
                        else "optional field added",
                    )
                )
            for name in sorted(before_properties.keys() & after_properties.keys()):
                child_before = before_properties[name]
                child_after = after_properties[name]
                if isinstance(child_before, dict) and isinstance(child_after, dict):
                    visit(child_before, child_after, f"{path}/{name}")
            for name in sorted((after_required - before_required) & before_properties.keys()):
                changes.append(
                    ContractChange(
                        f"{path}/{name}",
                        "field_became_required",
                        "breaking",
                        "existing optional field became required",
                    )
                )
        if (
            before.get("additionalProperties", True) is True
            and after.get("additionalProperties", True) is False
        ):
            changes.append(
                ContractChange(
                    path,
                    "additional_properties_closed",
                    "breaking",
                    "previously accepted unknown fields are now rejected",
                )
            )

    visit(old, new, "$")
    unique = {(item.path, item.kind, item.severity, item.detail): item for item in changes}
    ordered = tuple(unique[key] for key in sorted(unique))
    return ContractDiff(ordered)
