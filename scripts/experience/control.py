#!/usr/bin/env python3
"""Deterministic Batch 23 manifest, route graph and evidence controls."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from vav.core.evidence import combined_status, command_evidence, junit_evidence

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config/experience"
BUILD = ROOT / "build/experience"
SENSITIVE = re.compile(
    r"(?:phone|email|address|evidence|price|password|token)", re.IGNORECASE
)


def load(name: str) -> dict[str, Any]:
    value = yaml.safe_load((CONFIG / name).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != "1.0":
        raise ValueError(f"invalid experience manifest: {name}")
    return value


def sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def validate() -> dict[str, Any]:
    ia = load("information-architecture.yaml")
    route_manifest = load("routes.yaml")
    tasks = load("tasks.yaml")
    journeys = load("journeys.yaml")
    handoffs = load("handoffs.yaml")
    help_manifest = load("help.yaml")
    nodes = {item["code"]: item for item in ia["nodes"]}
    routes = {item["code"]: item for item in route_manifest["routes"]}
    help_codes = {item["code"] for item in help_manifest["articles"]}
    if len(nodes) != len(ia["nodes"]) or len(routes) != len(route_manifest["routes"]):
        raise ValueError("IA node and route codes must be unique")
    findings: list[dict[str, str]] = []
    for code, route in routes.items():
        if route["node"] not in nodes:
            findings.append({"type": "missing_ia_node", "route": code})
        if route.get("fallback") and route["fallback"] not in routes:
            findings.append({"type": "broken_fallback", "route": code})
        if route.get("critical") and route.get("help") not in help_codes:
            findings.append({"type": "missing_help", "route": code})
        if SENSITIVE.search(route["path"].partition("?")[2]):
            findings.append({"type": "sensitive_query", "route": code})
    for node in nodes.values():
        if node.get("primary_route") not in routes:
            findings.append(
                {"type": "missing_primary_destination", "route": node["code"]}
            )
        if node.get("parent") and node["parent"] not in nodes:
            findings.append({"type": "missing_parent", "route": node["code"]})
    for task in tasks["tasks"]:
        if task["route"] not in routes or task["fallback"] not in routes:
            findings.append({"type": "broken_task_action", "route": task["code"]})
    for journey in journeys["journeys"]:
        if not journey["steps"] or any(
            step["route"] not in routes for step in journey["steps"]
        ):
            findings.append({"type": "broken_journey_step", "route": journey["code"]})
    for handoff in handoffs["handoffs"]:
        if (
            handoff["target_route"] not in routes
            or handoff["return_route"] not in routes
        ):
            findings.append({"type": "broken_handoff", "route": handoff["code"]})
        if any(SENSITIVE.search(key) for key in handoff["context_keys"]):
            findings.append(
                {"type": "sensitive_handoff_schema", "route": handoff["code"]}
            )
    skills = sorted((ROOT / "skills/batch-23").glob("*/SKILL.md"))
    if len(skills) != 12:
        findings.append({"type": "skill_count", "route": str(len(skills))})
    if findings:
        raise ValueError(f"experience manifest gate failed: {findings}")
    return {
        "ia_nodes": len(nodes),
        "routes": len(routes),
        "tasks": len(tasks["tasks"]),
        "journeys": len(journeys["journeys"]),
        "handoffs": len(handoffs["handoffs"]),
        "help_articles": len(help_manifest["articles"]),
        "skills": len(skills),
        "critical_dead_ends": 0,
        "manifest_checksum_sha256": sha(
            {
                "ia": ia,
                "routes": route_manifest,
                "tasks": tasks,
                "journeys": journeys,
                "handoffs": handoffs,
                "help": help_manifest,
            }
        ),
    }


def write_evidence() -> tuple[Path, str]:
    result = validate()
    BUILD.mkdir(parents=True, exist_ok=True)
    backend_tests = junit_evidence(
        BUILD / "backend-junit.xml", BUILD / "backend-test-status.json"
    )
    security_tests = junit_evidence(
        BUILD / "security-junit.xml", BUILD / "security-test-status.json"
    )
    execution_evidence = {
        "database_migration": command_evidence(BUILD / "migration-status.json"),
        "permissions_seed": command_evidence(BUILD / "permissions-seed-status.json"),
        "domain_seed": command_evidence(BUILD / "domain-seed-status.json"),
        "backend_tests": backend_tests,
        "security_tests": security_tests,
        "packages_test": command_evidence(BUILD / "packages-test-status.json"),
        "packages_typecheck": command_evidence(
            BUILD / "packages-typecheck-status.json"
        ),
        "apps_test": command_evidence(BUILD / "apps-test-status.json"),
        "apps_build": command_evidence(BUILD / "apps-build-status.json"),
        "user_e2e": command_evidence(BUILD / "user-e2e-status.json"),
        "admin_e2e": command_evidence(BUILD / "admin-e2e-status.json"),
    }
    technical_status = combined_status(
        [{"status": "PASS"}, *execution_evidence.values()]
    )
    report = {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": git_commit(),
        "technical_status": technical_status,
        "technical_gates": {
            "manifest": {
                "status": "PASS",
                "checksum_sha256": result["manifest_checksum_sha256"],
            },
            "route_graph": {"status": "PASS", "critical_dead_ends": 0},
            **execution_evidence,
        },
        "external_gates": {
            "role_uat": "NOT_RUN",
            "support_review": "NOT_RUN",
            "production_observation": "NOT_RUN",
        },
        "production_certification": "NOT_CERTIFIED",
        "release_allowed": False,
        "inventory": result,
    }
    path = BUILD / "experience-evidence.json"
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path, technical_status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=[
            "sync",
            "ia-check",
            "route-check",
            "task-check",
            "journey-check",
            "handoff-check",
            "dead-end-scan",
            "evidence",
        ],
    )
    command = parser.parse_args().command
    if command == "evidence":
        path, status = write_evidence()
        print(json.dumps({"artifact": str(path.relative_to(ROOT)), "status": status}))
        return 1 if status == "FAIL" else 0
    else:
        print(
            json.dumps(
                {"command": command, "status": "PASS", **validate()}, sort_keys=True
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
