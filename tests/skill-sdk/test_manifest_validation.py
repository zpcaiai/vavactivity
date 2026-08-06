from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from vav_skill_sdk.manifest import ManifestValidationError, validate_manifest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "skill-packs/examples/vav.example.echo"
SCHEMA = ROOT / "schemas/skill-manifest.schema.json"


def _copy(tmp_path: Path) -> Path:
    target = tmp_path / "skill"
    shutil.copytree(EXAMPLE, target)
    return target


def _mutate(path: Path, callback: object) -> None:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert callable(callback)
    callback(payload)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_valid_manifest_and_referenced_schemas() -> None:
    manifest = validate_manifest(EXAMPLE / "skill.yaml", schema_path=SCHEMA)
    assert manifest.metadata.name == "vav.example.echo"
    assert manifest.spec.execution.timeout_seconds == 5


def test_unknown_manifest_fields_are_rejected(tmp_path: Path) -> None:
    package = _copy(tmp_path)
    _mutate(
        package / "skill.yaml", lambda payload: payload["spec"].update({"shell": "id"})
    )
    with pytest.raises(ManifestValidationError, match="Additional properties"):
        validate_manifest(package / "skill.yaml", schema_path=SCHEMA)


def test_wildcard_permissions_are_rejected(tmp_path: Path) -> None:
    package = _copy(tmp_path)
    _mutate(
        package / "skill.yaml",
        lambda payload: payload["spec"].update({"permissions": ["admin.*"]}),
    )
    with pytest.raises(ManifestValidationError):
        validate_manifest(package / "skill.yaml", schema_path=SCHEMA)


def test_side_effecting_skill_requires_idempotency(tmp_path: Path) -> None:
    package = _copy(tmp_path)

    def mutate(payload: dict[str, object]) -> None:
        spec = payload["spec"]
        assert isinstance(spec, dict)
        spec["type"] = "command"

    _mutate(package / "skill.yaml", mutate)
    with pytest.raises(ManifestValidationError, match="idempotency"):
        validate_manifest(package / "skill.yaml", schema_path=SCHEMA)


def test_schema_must_reject_unknown_input_fields(tmp_path: Path) -> None:
    package = _copy(tmp_path)
    schema = package / "schemas/input.schema.json"
    schema.write_text('{"type":"object","properties":{}}', encoding="utf-8")
    with pytest.raises(ManifestValidationError, match="additionalProperties=false"):
        validate_manifest(package / "skill.yaml", schema_path=SCHEMA)
