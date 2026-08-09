#!/usr/bin/env python3
# ruff: noqa: E501
"""Deterministic Batch 21 inventory, gap and certification controls."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from vav.core.evidence import combined_status, command_evidence, junit_evidence

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build" / "quality"
MANIFEST = ROOT / "quality-manifest.yaml"
WEB_ROOT = Path(
    os.environ.get("VAV_WEB_ROOT", str(ROOT.parent / "vavactivityWeb"))
).resolve()
ALLOWED_OPERATORS = {
    "eq",
    "neq",
    "gt",
    "gte",
    "lt",
    "lte",
    "contains",
    "all_passed",
    "none_open",
}
CRITICAL = {"blocker", "critical"}


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must contain an object")
    return value


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def commit() -> str:
    supplied = os.environ.get("VAV_GIT_COMMIT")
    if supplied:
        if not re.fullmatch(r"[0-9a-f]{40}", supplied):
            raise ValueError("VAV_GIT_COMMIT must be a full lowercase Git commit")
        return supplied
    try:
        value = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("Git commit identity is unavailable") from exc
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("Git returned an invalid commit identity")
    return value


def write_report(name: str, payload: dict[str, Any]) -> Path:
    BUILD.mkdir(parents=True, exist_ok=True)
    path = BUILD / name
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def validate_manifest() -> dict[str, Any]:
    value = load_yaml(MANIFEST)
    if value.get("schema_version") != "1.0.0":
        raise ValueError("unsupported quality manifest version")
    requirements = value.get("requirements", [])
    codes = [item.get("code") for item in requirements]
    if len(requirements) < 21 or len(codes) != len(set(codes)):
        raise ValueError(
            "project and Batches 1-20 require separate unique requirements"
        )
    for item in requirements:
        if not re.fullmatch(r"REQ-VAV-[A-Z0-9-]+-\d{3,}", str(item.get("code"))):
            raise ValueError(f"invalid requirement code: {item.get('code')}")
        if item.get("criticality") in CRITICAL and not item.get("module"):
            raise ValueError(f"critical requirement has no owner: {item.get('code')}")
    gate_codes = set()
    for gate in value.get("gates", []):
        if gate.get("operator") not in ALLOWED_OPERATORS:
            raise ValueError(f"unsafe gate operator: {gate.get('operator')}")
        if gate.get("code") in gate_codes:
            raise ValueError(f"duplicate gate: {gate.get('code')}")
        gate_codes.add(gate.get("code"))
    declared_non_waivable = set(value["constitution"]["non_waivable_gates"])
    if not declared_non_waivable <= gate_codes:
        raise ValueError("non-waivable gate definition is missing")
    skill_files = sorted((ROOT / "skills/batch-21").glob("*/SKILL.md"))
    if len(skill_files) != 12:
        raise ValueError(
            f"Batch 21 must contain exactly 12 child Skills, found {len(skill_files)}"
        )
    return value


def build_inventory() -> dict[str, Any]:
    manifest = validate_manifest()
    module_root = ROOT / "services/api/src/vav/modules"
    modules: dict[str, Any] = {}
    for path in sorted(module_root.glob("*/module.yaml")):
        item = load_yaml(path)
        code = item["module"]["code"]
        modules[code] = {
            "manifest": str(path.relative_to(ROOT)),
            "manifest_sha256": digest(path),
            "revisions": item["database"]["revisions"],
            "permissions": item["permissions"]["prefixes"],
            "events": item["events"],
            "health": item["health"]["checks"],
        }
    openapi_path = ROOT / "packages/contracts/openapi.json"
    openapi = json.loads(openapi_path.read_text(encoding="utf-8"))
    operations = [
        {
            "method": method.upper(),
            "path": path,
            "operation_id": operation["operationId"],
        }
        for path, methods in sorted(openapi["paths"].items())
        for method, operation in sorted(methods.items())
        if method.lower() in {"get", "post", "put", "patch", "delete"}
    ]
    pages = [
        {
            "path": str(path.relative_to(WEB_ROOT)),
            "sha256": digest(path),
        }
        for app in ("user-web", "admin-web")
        for path in sorted((WEB_ROOT / "apps" / app / "src").glob("**/pages/*.vue"))
    ]
    tests = [
        str(path.relative_to(source_root))
        for source_root in (ROOT, WEB_ROOT)
        for root in (
            (ROOT / "services/api/tests", ROOT / "tests")
            if source_root == ROOT
            else (WEB_ROOT / "e2e",)
        )
        if root.exists()
        for path in sorted(
            root.rglob("test_*.py" if root.name != "e2e" else "*.spec.ts")
        )
    ]
    return {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": commit(),
        "manifest_sha256": digest(MANIFEST),
        "modules": modules,
        "migrations": sorted(
            str(path.relative_to(ROOT))
            for path in (ROOT / "services/api/migrations/versions").glob("*.py")
        ),
        "pages": pages,
        "api_operations": operations,
        "events": load_yaml(ROOT / "config/events/manifest.yaml")["events"],
        "tests": tests,
        "requirement_count": len(manifest["requirements"]),
    }


def trace_checks(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    manifest = validate_manifest()
    checks: list[dict[str, Any]] = []
    migration_sources = "\n".join(inventory["migrations"])
    for requirement in manifest["requirements"]:
        module = requirement["module"]
        module_item = inventory["modules"].get(module)
        module_dir = ROOT / "services/api/src/vav/modules" / module
        test_dir = ROOT / "services/api/tests" / module
        if module == "ai_assistant":
            test_dir = ROOT / "services/api/tests/ai_assistant"
        path_checks = {
            "module_contract": module_item is not None,
            "application_service": (module_dir / "service.py").is_file()
            or (module_dir / "router.py").is_file(),
            "api_entry": (module_dir / "router.py").is_file()
            or (module_dir / "admin_router.py").is_file(),
            "database_revision": bool(module_item)
            and all(
                f"_{number:04d}_" in migration_sources
                for number in module_item["revisions"]
            ),
            "permission_owner": bool(module_item and module_item["permissions"]),
            "health_contract": bool(module_item and module_item["health"]),
            "tests": test_dir.exists(),
        }
        checks.append(
            {
                "requirement_code": requirement["code"],
                "module": module,
                "criticality": requirement["criticality"],
                "checks": path_checks,
                "complete": all(path_checks.values()),
            }
        )
    return checks


def closure_checks() -> list[dict[str, Any]]:
    required = {
        "code",
        "name",
        "criticality",
        "entry",
        "success_terminal",
        "failure_terminal",
        "cancel_or_expire",
        "admin_recovery",
        "manual_intervention",
    }
    return [
        {
            "flow_code": item.get("code"),
            "missing": sorted(required - set(item)),
            "complete": required <= set(item)
            and all(item.get(key) for key in required),
        }
        for item in validate_manifest()["business_flows"]
    ]


def detect_gaps(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for trace in trace_checks(inventory):
        for check, passed in trace["checks"].items():
            if not passed:
                gaps.append(
                    {
                        "gap_code": f"GAP-{trace['requirement_code']}-{check}".upper().replace(
                            "_", "-"
                        ),
                        "type": f"missing_{check}",
                        "severity": trace["criticality"],
                        "requirement_code": trace["requirement_code"],
                        "owner_team": f"{trace['module']}_engineering",
                        "status": "open",
                    }
                )
    for flow in closure_checks():
        if not flow["complete"]:
            gaps.append(
                {
                    "gap_code": f"GAP-{flow['flow_code']}-CLOSURE",
                    "type": "incomplete_business_flow",
                    "severity": "blocker",
                    "owner_team": "quality_engineering",
                    "status": "open",
                }
            )
    return gaps


def technical_report() -> dict[str, Any]:
    inventory = build_inventory()
    traces = trace_checks(inventory)
    flows = closure_checks()
    gaps = detect_gaps(inventory)
    critical_gaps = [item for item in gaps if item["severity"] in CRITICAL]
    automated_tests = {
        "database_migration": command_evidence(BUILD / "migration-status.json"),
        "permissions_seed": command_evidence(BUILD / "permissions-seed-status.json"),
        "domain_seed": command_evidence(BUILD / "domain-seed-status.json"),
        "backend": junit_evidence(
            BUILD / "backend-junit.xml", BUILD / "backend-test-status.json"
        ),
        "release_gates": junit_evidence(
            BUILD / "gate-junit.xml", BUILD / "gate-test-status.json"
        ),
        "security": junit_evidence(
            BUILD / "security-junit.xml", BUILD / "security-test-status.json"
        ),
        "admin_e2e": command_evidence(BUILD / "admin-e2e-status.json"),
    }
    structural = {"status": "PASS" if not critical_gaps else "FAIL"}
    technical_status = combined_status([structural, *automated_tests.values()])
    return {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": inventory["git_commit"],
        "technical_status": technical_status,
        "production_certification": "NOT_CERTIFIED",
        "release_allowed": False,
        "counts": {
            "modules": len(inventory["modules"]),
            "pages": len(inventory["pages"]),
            "api_operations": len(inventory["api_operations"]),
            "tests": len(inventory["tests"]),
            "requirements": len(traces),
            "complete_traces": sum(item["complete"] for item in traces),
            "complete_flows": sum(item["complete"] for item in flows),
            "critical_gaps": len(critical_gaps),
        },
        "automated_tests": automated_tests,
        "external_evidence": {
            "penetration_test": "NOT_RUN",
            "restore_drill": "NOT_RUN",
            "uat_approval": "NOT_RUN",
            "production_approval": "NOT_RUN",
        },
    }


def run(action: str) -> int:
    inventory = build_inventory()
    if action in {"manifest-check", "requirements-import"}:
        result = {"status": "PASS", "requirements": inventory["requirement_count"]}
    elif action in {"sync", "capabilities-sync"}:
        path = write_report("inventory.json", inventory)
        result = {"status": "PASS", "artifact": str(path.relative_to(ROOT))}
    elif action in {"trace-build", "trace-check"}:
        checks = trace_checks(inventory)
        path = write_report(
            "traceability.json", {"git_commit": commit(), "checks": checks}
        )
        failed = [
            item
            for item in checks
            if item["criticality"] in CRITICAL and not item["complete"]
        ]
        result = {
            "status": "PASS" if not failed else "FAIL",
            "artifact": str(path.relative_to(ROOT)),
            "critical_failures": len(failed),
        }
    elif action == "closure-check":
        checks = closure_checks()
        path = write_report(
            "business-closure.json", {"git_commit": commit(), "checks": checks}
        )
        result = {
            "status": "PASS" if all(item["complete"] for item in checks) else "FAIL",
            "artifact": str(path.relative_to(ROOT)),
        }
    elif action == "gap-check":
        gaps = detect_gaps(inventory)
        path = write_report("gaps.json", {"git_commit": commit(), "gaps": gaps})
        critical = [item for item in gaps if item["severity"] in CRITICAL]
        result = {
            "status": "PASS" if not critical else "FAIL",
            "artifact": str(path.relative_to(ROOT)),
            "critical_gaps": len(critical),
        }
    elif action in {"evidence-build", "release-report"}:
        report = technical_report()
        path = write_report("release-quality-report.json", report)
        result = {
            "status": report["technical_status"],
            "production_certification": "NOT_CERTIFIED",
            "artifact": str(path.relative_to(ROOT)),
        }
    elif action == "release-certify":
        result = {
            "status": "NOT_CERTIFIED",
            "reason": "independent production evidence and approval are required",
        }
    else:
        raise ValueError(f"unsupported quality action: {action}")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in {"PASS", "NOT_CERTIFIED", "NOT_RUN"} else 1


def parse_action(parts: list[str]) -> str:
    aliases: dict[tuple[str, ...], str] = {
        ("requirements", "import"): "requirements-import",
        ("capabilities", "sync"): "capabilities-sync",
        ("trace", "build"): "trace-build",
        ("trace", "validate"): "trace-check",
        ("flows", "validate"): "closure-check",
        ("gaps", "detect"): "gap-check",
        ("evidence", "collect"): "evidence-build",
        ("gates", "run"): "release-report",
        ("release", "report"): "release-report",
        ("release", "certify"): "release-certify",
    }
    return aliases.get(tuple(parts), "-".join(parts))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="+", help="quality control action")
    args = parser.parse_args()
    try:
        return run(parse_action(args.command))
    except (OSError, ValueError, KeyError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise SystemExit(f"quality control failed: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
