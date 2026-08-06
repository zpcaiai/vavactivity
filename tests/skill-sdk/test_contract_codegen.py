from __future__ import annotations

import json
from pathlib import Path

from vav_skill_contracts import compare_schemas, generate_contracts


def _schema(*, required: list[str], properties: dict[str, object]) -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": required,
        "properties": properties,
        "additionalProperties": False,
    }


def test_schema_diff_requires_major_for_removed_or_new_required_fields() -> None:
    old = _schema(required=["name"], properties={"name": {"type": "string"}})
    removed = _schema(required=[], properties={})
    new_required = _schema(
        required=["name", "age"],
        properties={"name": {"type": "string"}, "age": {"type": "integer"}},
    )
    assert compare_schemas(old, removed).require_version() == "major"
    assert compare_schemas(old, new_required).require_version() == "major"


def test_schema_diff_preserves_sensitive_annotation_review() -> None:
    old = _schema(
        required=[],
        properties={"email": {"type": "string", "x-vav-classification": "internal"}},
    )
    new = _schema(
        required=[],
        properties={"email": {"type": "string", "x-vav-classification": "restricted"}},
    )
    diff = compare_schemas(old, new)
    assert diff.review_required is True
    assert diff.require_version() == "minor"


def test_codegen_is_deterministic_and_emits_strict_models(tmp_path: Path) -> None:
    schema_path = tmp_path / "input.schema.json"
    schema_path.write_text(
        json.dumps(
            _schema(
                required=["locale"],
                properties={
                    "locale": {"type": "string"},
                    "limit": {"type": ["integer", "null"]},
                },
            )
        ),
        encoding="utf-8",
    )
    first = generate_contracts(schema_path, tmp_path / "generated", name="search_input")
    before = first.python_path.read_bytes(), first.typescript_path.read_bytes()
    second = generate_contracts(
        schema_path, tmp_path / "generated", name="search_input"
    )
    assert before == (
        second.python_path.read_bytes(),
        second.typescript_path.read_bytes(),
    )
    assert 'extra="forbid"' in second.python_path.read_text(encoding="utf-8")
    assert "readonly locale: string" in second.typescript_path.read_text(
        encoding="utf-8"
    )
