from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from vav.core.evidence import combined_status, command_evidence, junit_evidence

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build/admin"


def _git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def inspect(command: str) -> dict[str, Any]:
    manifest = yaml.safe_load(
        (ROOT / "config/admin-platform/manifest.yaml").read_text(encoding="utf-8")
    )
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "1.0":
        raise ValueError("invalid admin-platform manifest")
    capabilities = manifest["capabilities"]
    findings: list[str] = []
    domains = set(manifest["domains"]) | {"admin_platform"}
    approval_codes = {item["code"] for item in manifest["approval_policies"]}
    collections = {
        "capability": capabilities,
        "query": manifest["queries"],
        "bulk_operation": manifest["bulk_operations"],
        "approval_policy": manifest["approval_policies"],
        "field_policy": manifest["field_policies"],
    }
    for name, items in collections.items():
        codes = [item.get("code") for item in items]
        if len(codes) != len(set(codes)) or any(not code for code in codes):
            findings.append(f"{name}:duplicate-or-missing-code")
    for item in capabilities:
        if item.get("owner") not in domains:
            findings.append(f"{item['code']}:unknown-owner")
        if not item.get("permission") or not item.get("route"):
            findings.append(f"{item['code']}:missing-access-contract")
        if item["type"] not in {"view", "search"} and not item.get("command"):
            findings.append(f"{item['code']}:missing-domain-command")
        if (
            item["risk"] in {"high", "critical"}
            and item["type"] not in {"view", "search"}
            and not item.get("approval")
        ):
            findings.append(f"{item['code']}:missing-approval")
        if item.get("approval") and item["approval"] not in approval_codes:
            findings.append(f"{item['code']}:unknown-approval")
    for item in manifest["bulk_operations"]:
        if not 0 < int(item.get("maximum", 0)) <= 1000:
            findings.append(f"{item['code']}:unsafe-maximum")
        if item["risk"] in {"high", "critical"} and not item.get("approval"):
            findings.append(f"{item['code']}:missing-approval")
        if item.get("approval") and item["approval"] not in approval_codes:
            findings.append(f"{item['code']}:unknown-approval")
    skill_count = len(list((ROOT / "skills/batch-26").glob("[0-9][0-9]-*/SKILL.md")))
    if skill_count != 12:
        findings.append(f"skills:expected-12:found-{skill_count}")
    for item in manifest["field_policies"]:
        if item["classification"] == "highly_restricted" and item["reveal"]:
            findings.append("masking:highly-restricted-reveal-enabled")
        if item["reveal"] and (
            not item.get("purpose")
            or not item.get("permission")
            or not item.get("step_up")
        ):
            findings.append(f"{item['code']}:unsafe-reveal-policy")
    payload = {
        "command": command,
        "capabilities": len(capabilities),
        "domains": len(manifest["domains"]),
        "queries": len(manifest["queries"]),
        "bulk_operations": len(manifest["bulk_operations"]),
        "approval_policies": len(manifest["approval_policies"]),
        "field_policies": len(manifest["field_policies"]),
        "skills": skill_count,
        "findings": findings,
        "status": "PASS" if not findings else "FAIL",
    }
    payload["manifest_checksum_sha256"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode()
    ).hexdigest()
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("sync", "capability-check", "evidence"))
    command = parser.parse_args().command
    result = inspect(command)
    if command == "evidence":
        BUILD.mkdir(parents=True, exist_ok=True)
        evidence = {
            "database_migration": command_evidence(BUILD / "migration-status.json"),
            "permissions_seed": command_evidence(
                BUILD / "permissions-seed-status.json"
            ),
            "domain_seed": command_evidence(BUILD / "domain-seed-status.json"),
            "backend_tests": junit_evidence(
                BUILD / "backend-junit.xml", BUILD / "backend-test-status.json"
            ),
            "frontend_tests": command_evidence(
                ROOT / "build/shared/admin-web-test-status.json"
            ),
            "frontend_build": command_evidence(
                ROOT / "build/shared/admin-web-build-status.json"
            ),
            "browser_e2e": command_evidence(BUILD / "browser-e2e-status.json"),
        }
        technical_status = combined_status(
            [{"status": result["status"]}, *evidence.values()]
        )
        report = {
            "schema_version": "1.0.0",
            **result,
            "generated_at": datetime.now(UTC).isoformat(),
            "git_commit": _git_commit(),
            "technical_status": technical_status,
            "evidence": evidence,
            "production_certification": "NOT_CERTIFIED",
            "release_allowed": False,
        }
        output = BUILD / "admin-completeness-evidence.json"
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(
            json.dumps(
                {
                    "artifact": str(output.relative_to(ROOT)),
                    "status": technical_status,
                },
                sort_keys=True,
            )
        )
        return 1 if technical_status == "FAIL" else 0
    else:
        print(json.dumps(result, sort_keys=True))
    if result["status"] != "PASS":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
