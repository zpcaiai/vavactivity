from __future__ import annotations

import pytest

from vav_skill_testkit import PermissionProbe, SchemaValidator


def test_permission_probe_denies_undeclared_permissions() -> None:
    probe = PermissionProbe(frozenset({"knowledge.search.internal"}))
    probe.require("knowledge.search.internal")
    probe.assert_all_declared_used()
    with pytest.raises(PermissionError, match="undeclared"):
        probe.require("privacy.exports.create")


def test_schema_validator_rejects_additional_fields() -> None:
    validator = SchemaValidator(
        {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "additionalProperties": False,
        }
    )
    validator.validate({"value": "ok"})
    with pytest.raises(ValueError):
        validator.validate({"value": "ok", "injected": True})
