"""Offline manifest gates and evidence builder for Batch 24."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, cast

import yaml

from vav.modules.process_governance.domain import (
    simulate_faults,
    validate_process,
    verify_state_machine,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config/process"
BUILD = ROOT / "build/process"


def _load(name: str) -> dict[str, Any]:
    return cast(
        dict[str, Any], yaml.safe_load((CONFIG / name).read_text(encoding="utf-8"))
    )


def _snapshot() -> dict[str, Any]:
    processes = _load("business-processes.yaml")["processes"]
    machines = _load("state-machines.yaml")["machines"]
    compensations = _load("compensations.yaml")["compensations"]
    scenarios = _load("simulations.yaml")["scenarios"]
    process_findings = {item["code"]: validate_process(item) for item in processes}
    machine_findings = {item["code"]: verify_state_machine(item) for item in machines}
    simulation_results = {
        item["code"]: simulate_faults(
            item["process"], item["faults"], item["expected"]
        ).__dict__
        for item in scenarios
    }
    skill_count = len(list((ROOT / "skills/batch-24").glob("[0-9][0-9]-*/SKILL.md")))
    payload = {
        "processes": len(processes),
        "business_domains": sorted({item["domain"] for item in processes}),
        "state_machines": len(machines),
        "compensations": len(compensations),
        "simulations": len(scenarios),
        "skills": skill_count,
        "process_findings": process_findings,
        "state_machine_findings": machine_findings,
        "simulation_results": simulation_results,
    }
    payload["manifest_checksum_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()
    failures = (
        sum(bool(value) for value in process_findings.values())
        + sum(bool(value) for value in machine_findings.values())
        + sum(value["status"] != "pass" for value in simulation_results.values())
    )
    payload["status"] = (
        "PASS"
        if failures == 0 and skill_count == 12 and len(processes) >= 15
        else "FAIL"
    )
    return payload


def _git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=[
            "sync",
            "manifest-check",
            "state-machine-check",
            "simulation-check",
            "evidence",
        ],
    )
    args = parser.parse_args()
    snapshot = _snapshot()
    if args.command == "evidence":
        BUILD.mkdir(parents=True, exist_ok=True)
        report = {
            "batch": 24,
            "git_commit": _git_commit(),
            "technical_gate": snapshot,
            "database_migration": "PASS_IF_RECORDED_BY_CI",
            "backend_tests": "PASS_IF_JUNIT_PRESENT"
            if (BUILD / "backend-junit.xml").exists()
            else "NOT_RUN",
            "admin_e2e": "NOT_RUN",
            "external_provider_recovery": "NOT_RUN",
            "business_owner_acceptance": "NOT_RUN",
            "production_observation": "NOT_RUN",
            "production_certification": "NOT_CERTIFIED",
        }
        target = BUILD / "process-evidence.json"
        target.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        print(target)
        return
    print(
        json.dumps(
            {"command": args.command, **snapshot}, ensure_ascii=False, sort_keys=True
        )
    )
    if snapshot["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
