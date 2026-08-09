#!/usr/bin/env python3
"""Fail-closed validation for canonical schemas and every checked-in Skill package."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from vav_skill_sdk.manifest import validate_manifest


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    schema_paths = sorted((root / "schemas").glob("*.schema.json"))
    if len(schema_paths) < 7:
        raise SystemExit(
            "expected at least seven canonical Skill and Marketplace schemas"
        )
    for path in schema_paths:
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))
    packaged_manifest_schema = (
        root
        / "packages/skill-sdk-python/src/vav_skill_sdk/schemas/skill-manifest.schema.json"
    )
    if json.loads(packaged_manifest_schema.read_text(encoding="utf-8")) != json.loads(
        (root / "schemas/skill-manifest.schema.json").read_text(encoding="utf-8")
    ):
        raise SystemExit("packaged and repository Skill manifest schemas have drifted")
    manifests = sorted((root / "skill-packs").glob("*/*/skill.yaml"))
    if not manifests:
        raise SystemExit("no Skill packages were found")
    for manifest in manifests:
        validate_manifest(
            manifest, schema_path=root / "schemas/skill-manifest.schema.json"
        )
    print(
        f"Skill schema validation PASS: {len(schema_paths)} schemas, {len(manifests)} packages, packaged manifests synchronized"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
