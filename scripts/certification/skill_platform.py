#!/usr/bin/env python3
"""Build a fail-closed Batch 20 certification report bound to one Git commit."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_ARTIFACTS = (
    "schemas/skill-manifest.schema.json",
    "packages/skill-sdk-python/pyproject.toml",
    "packages/skill-sdk-typescript/package.json",
    "packages/skill-ui-sdk/package.json",
    "packages/skill-cli/pyproject.toml",
    "services/skill-runtime/pyproject.toml",
    "services/api/src/vav/modules/skills_platform/service.py",
    "services/api/src/vav/modules/skills_platform/registry_ingestion.py",
    "services/api/migrations/versions/20260806_0086_skill_registry_governance.py",
    "extensions/vav-skills-vscode/package.json",
    "apps/admin-web/src/pages/SkillManagementPage.vue",
    "registry/trust-roots.json",
    "registry/revoked-signatures.json",
)
REQUIRED_PRODUCTION_EVIDENCE = (
    "skill-sdk",
    "skill-schema",
    "skill-runtime",
    "skill-registry",
    "skill-security",
    "skill-marketplace",
    "skill-complete-e2e",
    "sandbox-escape",
    "signed-package",
    "revocation",
    "restore-drill",
    "production-run",
    "publisher-verification",
    "human-review",
    "production-approval",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def validate_registry() -> dict[str, str]:
    values: dict[str, str] = {}
    for name in (
        "builtin-index.json",
        "trust-roots.json",
        "revoked-signatures.json",
        "compatibility-matrix.json",
    ):
        path = ROOT / "registry" / name
        json.loads(path.read_text(encoding="utf-8"))
        values[name] = digest(path)
    return values


def load_evidence(directory: Path, commit: str) -> dict[str, Any]:
    collected: dict[str, Any] = {}
    for name in REQUIRED_PRODUCTION_EVIDENCE:
        path = directory / f"{name}.json"
        if not path.is_file():
            raise ValueError(f"missing production evidence: {path}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("status") != "PASS":
            raise ValueError(f"evidence is not PASS: {path}")
        if value.get("git_commit") != commit:
            raise ValueError(f"evidence commit mismatch: {path}")
        if not value.get("artifact_sha256") or not value.get("completed_at"):
            raise ValueError(f"evidence identity is incomplete: {path}")
        collected[name] = {
            "status": "PASS",
            "artifact_sha256": value["artifact_sha256"],
            "completed_at": value["completed_at"],
        }
    return collected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode", choices=("architecture", "production"), default="architecture"
    )
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "build/certification/skill-platform-release-manifest.json",
    )
    args = parser.parse_args()
    missing = [name for name in REQUIRED_ARTIFACTS if not (ROOT / name).is_file()]
    if missing:
        raise SystemExit(f"required Skill platform artifacts are missing: {missing}")
    commit = git_commit()
    evidence: dict[str, Any]
    if args.mode == "production":
        if args.evidence_dir is None or not args.evidence_dir.is_dir():
            raise SystemExit("--evidence-dir is required in production mode")
        try:
            evidence = load_evidence(args.evidence_dir, commit)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise SystemExit(str(exc)) from exc
        certification_level = "marketplace_verified"
        production_certification = "CERTIFIED"
    else:
        evidence = {
            name: {
                "status": "NOT_EVALUATED",
                "reason": "external evidence not supplied",
            }
            for name in REQUIRED_PRODUCTION_EVIDENCE
            if name
            in {
                "sandbox-escape",
                "signed-package",
                "restore-drill",
                "production-run",
                "publisher-verification",
                "human-review",
                "production-approval",
            }
        }
        certification_level = "tested"
        production_certification = "NOT_CERTIFIED"
    report = {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": commit,
        "technical_status": "PASS",
        "certification_level": certification_level,
        "production_certification": production_certification,
        "artifact_checksums": {
            name: digest(ROOT / name) for name in REQUIRED_ARTIFACTS
        },
        "registry_checksums": validate_registry(),
        "evidence": evidence,
        "release_allowed": production_certification == "CERTIFIED",
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{digest(output)}  {output.name}\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "technical_status",
                    "certification_level",
                    "production_certification",
                    "release_allowed",
                )
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
