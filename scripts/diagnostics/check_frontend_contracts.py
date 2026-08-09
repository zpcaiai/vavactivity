#!/usr/bin/env python3
"""Verify contracts handed from the backend to the split frontend repository."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PERMISSION_CONTRACT = ROOT / "config/frontend/admin-route-permissions.json"
REQUIRED_FRONTEND_ARTIFACTS = (
    "packages/skill-sdk-typescript/package.json",
    "packages/skill-ui-sdk/package.json",
    "extensions/vav-skills-vscode/package.json",
    "apps/admin-web/src/pages/SkillManagementPage.vue",
)


def fail(message: str) -> None:
    raise SystemExit(f"frontend handoff contract failed: {message}")


def load_json(path: Path) -> Any:
    if not path.is_file():
        fail(f"contract not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def verify_permissions(web_root: Path) -> int:
    contract = load_json(PERMISSION_CONTRACT)
    source = contract.get("source", {})
    router = web_root / str(source.get("path", ""))
    if not router.is_file():
        fail(f"router source not found: {router}")

    actual = set(
        re.findall(
            r"permission:\s*['\"]([a-z0-9_.]+)['\"]",
            router.read_text(encoding="utf-8"),
        )
    )
    declared_values = contract.get("permissions")
    if not isinstance(declared_values, list) or not declared_values:
        fail("permissions must be a non-empty list")
    declared = set(declared_values)
    if len(declared) != len(declared_values):
        fail("permissions must be unique")

    missing = sorted(declared - actual)
    extra = sorted(actual - declared)
    if missing or extra:
        fail(f"router drift detected; missing={missing}, extra={extra}")
    return len(actual)


def verify_json_handoff(backend: Path, frontend: Path, label: str) -> None:
    if load_json(backend) != load_json(frontend):
        fail(f"{label} drifted between backend and frontend repositories")


def main() -> None:
    web_root = Path(
        os.environ.get("VAV_WEB_ROOT", str(ROOT.parent / "vavactivityWeb"))
    ).resolve()
    missing = [
        path for path in REQUIRED_FRONTEND_ARTIFACTS if not (web_root / path).is_file()
    ]
    if missing:
        fail(f"required frontend artifacts are missing: {missing}")
    permission_count = verify_permissions(web_root)
    verify_json_handoff(
        ROOT / "packages/contracts/openapi.json",
        web_root / "packages/contracts/openapi.json",
        "OpenAPI contract",
    )
    verify_json_handoff(
        ROOT / "schemas/skill-manifest.schema.json",
        web_root / "extensions/vav-skills-vscode/schemas/skill-manifest.schema.json",
        "VS Code Skill manifest schema",
    )
    print(
        "frontend handoff contracts valid: "
        f"{len(REQUIRED_FRONTEND_ARTIFACTS)} Skill artifacts, OpenAPI, Skill schema, "
        f"and {permission_count} route permissions"
    )


if __name__ == "__main__":
    main()
