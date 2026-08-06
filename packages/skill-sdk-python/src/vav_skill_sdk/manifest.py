"""Load and validate immutable Skill manifests and their referenced schemas."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from pydantic import ValidationError

from vav_skill_sdk.models import SkillManifest
from vav_skill_sdk.permissions import validate_permissions

REQUIRED_PACKAGE_FILES = ("skill.yaml", "README.md", "CHANGELOG.md", "LICENSE")
FORBIDDEN_TEXT_MARKERS = (
    "docker.sock",
    "postgresql://",
    "postgresql+asyncpg://",
    "mysql://",
    "mongodb://",
    "BEGIN PRIVATE KEY",
    "BEGIN RSA PRIVATE KEY",
)


class ManifestValidationError(ValueError):
    pass


def _repository_schema(manifest_path: Path) -> Path:
    for parent in manifest_path.resolve().parents:
        candidate = parent / "schemas" / "skill-manifest.schema.json"
        if candidate.is_file():
            return candidate
    packaged = Path(__file__).with_name("schemas") / "skill-manifest.schema.json"
    if packaged.is_file():
        return packaged
    raise ManifestValidationError("canonical skill-manifest.schema.json was not found")


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ManifestValidationError(f"cannot read manifest: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ManifestValidationError("manifest root must be an object")
    return parsed


def _validate_referenced_schema(package_root: Path, relative: str) -> None:
    target = (package_root / relative).resolve()
    if package_root.resolve() not in target.parents:
        raise ManifestValidationError(f"schema escapes package root: {relative}")
    try:
        schema = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestValidationError(f"invalid referenced schema {relative}: {exc}") from exc
    Draft202012Validator.check_schema(schema)
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise ManifestValidationError(
            f"schema {relative} must be an object with additionalProperties=false"
        )


def validate_manifest(
    manifest_path: str | Path,
    *,
    schema_path: str | Path | None = None,
) -> SkillManifest:
    path = Path(manifest_path).resolve()
    if path.name != "skill.yaml":
        raise ManifestValidationError("canonical manifest filename is skill.yaml")
    package_root = path.parent
    missing = [name for name in REQUIRED_PACKAGE_FILES if not (package_root / name).is_file()]
    if missing:
        raise ManifestValidationError(f"required package files are missing: {missing}")

    raw_text = path.read_text(encoding="utf-8")
    marker = next((item for item in FORBIDDEN_TEXT_MARKERS if item in raw_text), None)
    if marker:
        raise ManifestValidationError(
            f"manifest contains forbidden secret or host marker: {marker}"
        )
    raw = _load_yaml_mapping(path)

    canonical_schema_path = Path(schema_path) if schema_path else _repository_schema(path)
    schema = json.loads(canonical_schema_path.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(raw), key=lambda item: list(item.path))
    if errors:
        detail = "; ".join(
            f"{'/'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
            for error in errors[:10]
        )
        raise ManifestValidationError(detail)
    try:
        manifest = SkillManifest.model_validate(raw)
    except ValidationError as exc:
        raise ManifestValidationError(str(exc)) from exc

    try:
        validate_permissions(manifest.spec.permissions)
    except ValueError as exc:
        raise ManifestValidationError(str(exc)) from exc
    for reference in (manifest.spec.inputs, manifest.spec.outputs, manifest.spec.errors):
        _validate_referenced_schema(package_root, reference.schema_path)
    return manifest


def load_manifest(manifest_path: str | Path) -> SkillManifest:
    return validate_manifest(manifest_path)
