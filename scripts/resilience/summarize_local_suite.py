#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result_dir", type=Path)
    args = parser.parse_args()
    root = args.result_dir
    restore_reports = sorted(root.glob("restore-drill-*.json"))
    chaos_reports = sorted(root.glob("chaos-*.json"))
    failures = []
    for path in restore_reports + chaos_reports:
        try:
            if json.loads(path.read_text(encoding="utf-8"))["status"] != "PASS":
                failures.append(path.name)
        except (json.JSONDecodeError, KeyError):
            failures.append(path.name)
    artifacts = [
        {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in sorted(root.iterdir())
        if path.is_file() and path.name != "suite-summary.json"
    ]
    summary = {
        "status": (
            "LOCAL_PASS"
            if restore_reports and len(chaos_reports) == 5 and not failures
            else "FAIL"
        ),
        "evidence_scope": "local_compose",
        "production_certification": False,
        "backup_restore": "LOCAL_PASS" if restore_reports and not failures else "FAIL",
        "chaos_recovery": "LOCAL_PASS"
        if len(chaos_reports) == 5 and not failures
        else "FAIL",
        "local_application_ha": "FAIL_SINGLE_INSTANCE_OUTAGE_CONFIRMED",
        "application_ha": "NOT_EVALUATED",
        "database_ha": "NOT_EVALUATED",
        "regional_dr": "NOT_EVALUATED",
        "rpo_rto_production": "NOT_EVALUATED",
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "worktree_clean": not subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
        ).stdout.strip(),
        "completed_at": datetime.now(UTC).isoformat(),
        "failures": failures,
        "artifacts": artifacts,
        "note": (
            "Single-instance Compose recovery and isolated restore do not prove production "
            "HA or regional DR."
        ),
    }
    (root / "suite-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if summary["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
