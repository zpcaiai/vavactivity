from __future__ import annotations

import pytest
from pydantic import ValidationError

from vav.modules.quality.schemas import GateDefinitionCreate


def test_gate_schema_rejects_arbitrary_execution_fields() -> None:
    with pytest.raises(ValidationError):
        GateDefinitionCreate.model_validate(
            {
                "gate_code": "GATE-TEST-SAFE",
                "semantic_version": "1.0.0",
                "name": "Safe test gate",
                "category": "test",
                "enforcement_level": "blocker",
                "condition_definition": {
                    "metric": "test_status",
                    "operator": "shell",
                    "expected": "pass",
                    "command": "curl metadata.internal",
                },
                "required_evidence_types": ["unit_test_report"],
                "applicable_release_types": ["standard"],
            }
        )
