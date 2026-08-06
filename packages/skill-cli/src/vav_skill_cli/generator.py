"""Safe, idempotent Skill package scaffolding."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

SKILL_TYPES = {
    "query",
    "command",
    "workflow",
    "agent-tool",
    "event-handler",
    "provider-adapter",
    "domain-pack",
}


def create_skill(root: str | Path, *, name: str, skill_type: str, runtime: str) -> Path:
    if skill_type not in SKILL_TYPES:
        raise ValueError(f"unsupported Skill template: {skill_type}")
    if runtime not in {"python", "typescript", "worker", "http", "sandbox", "none"}:
        raise ValueError(f"unsupported Skill runtime: {runtime}")
    target = Path(root).resolve()
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty directory: {target}")
    for directory in (
        target / "src",
        target / "schemas",
        target / "tests/unit",
        target / "tests/contract",
        target / "fixtures",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    side_effecting = skill_type in {"command", "workflow", "event-handler"}
    manifest = {
        "apiVersion": "skills.vav.io/v1",
        "kind": "Skill",
        "metadata": {
            "name": name,
            "displayName": name,
            "version": "0.1.0",
            "publisher": name.split(".")[0],
            "description": "Describe the Skill capability and its safety boundary.",
            "license": "UNLICENSED",
            "categories": [],
        },
        "spec": {
            "type": skill_type,
            "runtime": runtime,
            "entrypoint": "skill:SkillImplementation",
            "runtimeApiVersion": "1.0",
            "manifestVersion": "1.0",
            "inputs": {"schema": "schemas/input.schema.json"},
            "outputs": {"schema": "schemas/output.schema.json"},
            "errors": {"schema": "schemas/error.schema.json"},
            "permissions": [],
            "capabilities": {"provides": [], "requires": []},
            "dependencies": {"skills": [], "modules": [], "providers": []},
            "execution": {
                "timeoutSeconds": 30,
                "retryPolicy": "idempotent" if side_effecting else "read_safe",
                "idempotency": "required" if side_effecting else "not_required",
                "concurrencyLimit": 10,
            },
            "data": {"reads": [], "writes": []},
            "security": {
                "networkAccess": "none",
                "filesystemAccess": "none",
                "secretAccess": [],
                "riskLevel": "low",
                "userConfirmationRequired": side_effecting,
            },
            "compatibility": {
                "minimumPlatformVersion": "1.0.0",
                "maximumPlatformVersion": "1.x",
            },
            "observability": {"tracing": True, "metrics": True, "auditLevel": "metadata"},
            "tests": {"command": "pytest -q"},
        },
    }
    (target / "skill.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    (target / "README.md").write_text(
        f"# {name}\n\nGenerated VAV Skill package.\n", encoding="utf-8"
    )
    (target / "CHANGELOG.md").write_text(
        "# Changelog\n\n## 0.1.0\n\n- Initial scaffold.\n", encoding="utf-8"
    )
    (target / "LICENSE").write_text("UNLICENSED\n", encoding="utf-8")
    for kind in ("input", "output"):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"skills://{name}/0.1.0/{kind}",
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
        (target / f"schemas/{kind}.schema.json").write_text(
            json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    error_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"skills://{name}/0.1.0/error",
        "type": "object",
        "required": ["code", "message"],
        "properties": {
            "code": {"type": "string", "maxLength": 128},
            "message": {"type": "string", "maxLength": 500},
        },
        "additionalProperties": False,
    }
    (target / "schemas/error.schema.json").write_text(
        json.dumps(error_schema, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (target / "src/skill.py").write_text(
        '"""Generated Skill implementation."""\n\n'
        "class SkillImplementation:\n"
        "    async def execute(self, payload: dict[str, object], context: object) -> dict[str, object]:\n"
        "        return {}\n",
        encoding="utf-8",
    )
    return target
