#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def build_summary(
    root: Path, *, git_commit: str | None = None, worktree_clean: bool | None = None
) -> dict[str, object]:
    restore_reports = sorted(root.glob("restore-drill-*.json"))
    chaos_reports = sorted(root.glob("chaos-*.json"))
    ha_reports = sorted(root.glob("api-ha.json"))
    report_failures: dict[str, list[str]] = {
        "restore": [],
        "chaos": [],
        "ha": [],
    }
    for category, reports in (
        ("restore", restore_reports),
        ("chaos", chaos_reports),
        ("ha", ha_reports),
    ):
        for path in reports:
            try:
                if json.loads(path.read_text(encoding="utf-8"))["status"] != "PASS":
                    report_failures[category].append(path.name)
            except (json.JSONDecodeError, KeyError):
                report_failures[category].append(path.name)
    failures = [
        failure
        for category in ("restore", "chaos", "ha")
        for failure in report_failures[category]
    ]
    artifacts = [
        {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in sorted(root.iterdir())
        if path.is_file() and path.name != "suite-summary.json"
    ]
    if git_commit is None:
        git_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()
    if worktree_clean is None:
        worktree_clean = not subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
        ).stdout.strip()
    return {
        "status": (
            "LOCAL_PASS"
            if restore_reports
            and len(chaos_reports) == 5
            and len(ha_reports) == 1
            and not failures
            else "FAIL"
        ),
        "evidence_scope": "local_compose",
        "production_certification": False,
        "backup_restore": "LOCAL_PASS"
        if restore_reports and not report_failures["restore"]
        else "FAIL",
        "chaos_recovery": "LOCAL_PASS"
        if len(chaos_reports) == 5 and not report_failures["chaos"]
        else "FAIL",
        "local_application_ha": "LOCAL_PASS"
        if len(ha_reports) == 1 and not report_failures["ha"]
        else "FAIL",
        "application_ha": "NOT_EVALUATED",
        "database_ha": "NOT_EVALUATED",
        "regional_dr": "NOT_EVALUATED",
        "rpo_rto_production": "NOT_EVALUATED",
        "git_commit": git_commit,
        "worktree_clean": worktree_clean,
        "completed_at": datetime.now(UTC).isoformat(),
        "failures": failures,
        "artifacts": artifacts,
        "note": (
            "Two-instance local API failover, single-service recovery, and isolated restore "
            "do not prove production database HA or regional DR."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result_dir", type=Path)
    args = parser.parse_args()
    root = args.result_dir
    summary = build_summary(root)
    (root / "suite-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if summary["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
