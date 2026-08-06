"""Offline Batch 25 contract, lineage and integrity gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, cast

import yaml

from vav.modules.data_governance.domain import (
    contract_diff,
    validate_asset,
    validate_lineage,
    validate_rule,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config/data"
BUILD = ROOT / "build/data"


def _load(name: str) -> dict[str, Any]:
    return cast(
        dict[str, Any], yaml.safe_load((CONFIG / name).read_text(encoding="utf-8"))
    )


def _snapshot() -> dict[str, Any]:
    assets = _load("ownership.yaml")["assets"]
    contracts = _load("contracts.yaml")["contracts"]
    lineage = _load("lineage.yaml")["edges"]
    reconciliations = _load("reconciliations.yaml")["reconciliations"]
    rules = _load("quality-rules.yaml")["rules"]
    backfills = _load("backfills.yaml")["backfills"]
    asset_findings = {item["code"]: validate_asset(item) for item in assets}
    rule_findings = {item["code"]: validate_rule(item) for item in rules}
    lineage_findings = validate_lineage(assets, lineage)
    contract_assets = {item["asset"] for item in contracts}
    missing_contracts = sorted(
        asset["code"]
        for asset in assets
        if asset["truth"] and asset["code"] not in contract_assets
    )
    unsafe_repairs = sorted(
        item["repair"]
        for item in reconciliations
        if any(
            marker in item["repair"].casefold()
            for marker in ("direct_sql", "set_state", "mark_paid", "fabricate")
        )
    )
    self_diffs = {
        item["code"]: contract_diff(item, item)["compatibility_status"]
        for item in contracts
    }
    skills = len(list((ROOT / "skills/batch-25").glob("[0-9][0-9]-*/SKILL.md")))
    payload = {
        "assets": len(assets),
        "contracts": len(contracts),
        "lineage_edges": len(lineage),
        "reconciliations": len(reconciliations),
        "quality_rules": len(rules),
        "backfills": len(backfills),
        "skills": skills,
        "asset_findings": asset_findings,
        "lineage_findings": lineage_findings,
        "rule_findings": rule_findings,
        "critical_sources_missing_contracts": missing_contracts,
        "unsafe_repairs": unsafe_repairs,
        "contract_self_diffs": self_diffs,
    }
    payload["manifest_checksum_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()
    ).hexdigest()
    failures = (
        sum(bool(item) for item in asset_findings.values())
        + len(lineage_findings)
        + sum(bool(item) for item in rule_findings.values())
        + len(missing_contracts)
        + len(unsafe_repairs)
    )
    payload["status"] = (
        "PASS" if failures == 0 and skills == 12 and len(assets) >= 20 else "FAIL"
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
            "contract-check",
            "lineage-check",
            "quality-check",
            "evidence",
        ],
    )
    args = parser.parse_args()
    snapshot = _snapshot()
    if args.command == "evidence":
        BUILD.mkdir(parents=True, exist_ok=True)
        report = {
            "batch": 25,
            "git_commit": _git_commit(),
            "technical_gate": snapshot,
            "backend_tests": "PASS_IF_JUNIT_PRESENT"
            if (BUILD / "backend-junit.xml").exists()
            else "NOT_RUN",
            "admin_e2e": "NOT_RUN",
            "live_event_delivery": "NOT_RUN",
            "production_backfill": "NOT_RUN",
            "production_erasure_observation": "NOT_RUN",
            "production_certification": "NOT_CERTIFIED",
        }
        target = BUILD / "data-integrity-evidence.json"
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
