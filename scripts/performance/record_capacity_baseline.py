#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("summary", type=Path)
    parser.add_argument("--release", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--infrastructure", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    infrastructure = json.loads(args.infrastructure.read_text(encoding="utf-8"))
    metrics = summary.get("metrics", {})
    checks = metrics.get("checks", {}).get("values", {})
    status = "passed" if checks.get("rate", 0) >= 0.99 else "failed"
    record = {
        "schema_version": "1.0.0",
        "release_version": args.release,
        "environment": args.environment,
        "scenario_code": args.scenario,
        "infrastructure_snapshot": infrastructure,
        "load_snapshot": {
            "vus_max": metrics.get("vus_max", {}).get("values", {}).get("max")
        },
        "result_metrics": metrics,
        "status": status,
        "tested_at": datetime.now(UTC).isoformat(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if status != "passed":
        raise SystemExit("capacity baseline failed its check-rate gate")


if __name__ == "__main__":
    main()
