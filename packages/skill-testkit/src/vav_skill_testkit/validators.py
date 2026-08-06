"""Deterministic validators and permission probes for Skill packages."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]


class SchemaValidator:
    def __init__(self, schema: dict[str, Any]) -> None:
        Draft202012Validator.check_schema(schema)
        self._validator = Draft202012Validator(schema)

    def validate(self, payload: object) -> None:
        errors = sorted(self._validator.iter_errors(payload), key=lambda error: list(error.path))
        if errors:
            raise ValueError(errors[0].message)


class SnapshotValidator:
    def __init__(self, path: str | Path, *, update: bool = False) -> None:
        self.path = Path(path)
        self.update = update

    def assert_match(self, payload: object) -> None:
        canonical = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if self.update:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(canonical, encoding="utf-8")
            return
        if not self.path.is_file() or self.path.read_text(encoding="utf-8") != canonical:
            raise AssertionError(f"snapshot mismatch: {self.path}")


@dataclass
class PermissionProbe:
    declared: frozenset[str]
    used: set[str] = field(default_factory=set)

    def require(self, permission: str) -> None:
        if permission not in self.declared:
            raise PermissionError(f"undeclared Skill permission: {permission}")
        self.used.add(permission)

    def assert_all_declared_used(self) -> None:
        unused = self.declared - self.used
        if unused:
            raise AssertionError(f"declared permissions were not exercised: {sorted(unused)}")
