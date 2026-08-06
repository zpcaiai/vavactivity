from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]


def inspect(command: str) -> dict[str, Any]:
    manifest = yaml.safe_load((ROOT / "config/admin-platform/manifest.yaml").read_text())
    capabilities = manifest["capabilities"]
    findings: list[str] = []
    for item in capabilities:
        if item["type"] not in {"view", "search"} and not item.get("command"):
            findings.append(f"{item['code']}:missing-domain-command")
        if item["risk"] in {"high", "critical"} and item["type"] not in {"view", "search"} and not item.get("approval"):
            findings.append(f"{item['code']}:missing-approval")
    skill_count = len(list((ROOT / "skills/batch-26").glob("[0-9][0-9]-*/SKILL.md")))
    if skill_count != 12:
        findings.append(f"skills:expected-12:found-{skill_count}")
    if any(item["classification"] == "highly_restricted" and item["reveal"] for item in manifest["field_policies"]):
        findings.append("masking:highly-restricted-reveal-enabled")
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
    payload["manifest_checksum_sha256"] = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    return payload


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "sync"
    result = inspect(command)
    if command == "evidence":
        output = ROOT / "build/admin/admin-completeness-evidence.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        result["browser_e2e"] = "NOT_RUN"
        result["production_certification"] = "NOT_CERTIFIED"
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(output)
    else:
        print(json.dumps(result, sort_keys=True))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
