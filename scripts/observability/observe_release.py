#!/usr/bin/env python3
"""Sample release endpoints and evaluate observation windows using real elapsed time."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_ENDPOINTS = [
    "api=http://127.0.0.1:8000/api/v1/health/ready",
    "user=http://127.0.0.1:5173/zh-CN/",
    "admin=http://127.0.0.1:5174/admin/login",
]
WINDOWS = {"24h": 24 * 3600, "7d": 7 * 24 * 3600, "30d": 30 * 24 * 3600}


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_endpoint(value: str) -> tuple[str, str]:
    name, separator, url = value.partition("=")
    if not separator or not name or not url.startswith(("http://", "https://")):
        raise argparse.ArgumentTypeError("endpoint must be NAME=http(s)://URL")
    return name, url


def git_state() -> tuple[str, bool]:
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
    ).stdout.strip()
    return commit, not bool(dirty)


def probe(url: str, timeout: float) -> dict[str, object]:
    request = urllib.request.Request(
        url, headers={"User-Agent": "vav-release-observer/1"}
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    started = time.monotonic()
    try:
        with opener.open(request, timeout=timeout) as response:
            response.read(1024)
            status = response.status
            error = None
    except urllib.error.HTTPError as exc:
        status = exc.code
        error = f"HTTP {exc.code}"
    except (OSError, urllib.error.URLError) as exc:
        status = None
        error = str(exc)
    return {
        "url": url,
        "status_code": status,
        "latency_ms": round((time.monotonic() - started) * 1000, 2),
        "ok": status is not None and 200 <= status < 400,
        "error": error,
    }


def append_sample(
    state: Path, endpoints: list[tuple[str, str]], timeout: float, scope: str
) -> dict[str, object]:
    commit, clean = git_state()
    checks = {name: probe(url, timeout) for name, url in endpoints}
    sample = {
        "sampled_at": utc_now().isoformat(),
        "epoch_seconds": time.time(),
        "status": "PASS" if all(item["ok"] for item in checks.values()) else "FAIL",
        "evidence_scope": scope,
        "production_certification": False,
        "git_commit": commit,
        "worktree_clean": clean,
        "checks": checks,
    }
    state.parent.mkdir(parents=True, exist_ok=True)
    with state.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(sample, sort_keys=True) + "\n")
    return sample


def load_samples(state: Path) -> list[dict[str, object]]:
    if not state.exists():
        return []
    return [
        json.loads(line)
        for line in state.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def evaluate(state: Path, expected_interval: int) -> dict[str, object]:
    samples = sorted(
        load_samples(state), key=lambda sample: float(sample["epoch_seconds"])
    )
    now = time.time()
    outcomes: dict[str, object] = {}
    for label, seconds in WINDOWS.items():
        cutoff = now - seconds
        before_cutoff = [
            sample for sample in samples if float(sample["epoch_seconds"]) <= cutoff
        ]
        within_window = [
            sample for sample in samples if float(sample["epoch_seconds"]) > cutoff
        ]
        anchor = before_cutoff[-1:] if before_cutoff else []
        coverage_samples = anchor + within_window
        elapsed = 0.0 if not samples else now - float(samples[0]["epoch_seconds"])
        timestamps = [float(sample["epoch_seconds"]) for sample in coverage_samples]
        gaps = [
            right - left
            for left, right in zip(timestamps, timestamps[1:], strict=False)
        ]
        latest_age = 0.0 if not timestamps else now - timestamps[-1]
        coverage_complete = bool(anchor and within_window) and latest_age <= (
            expected_interval * 2
        )
        cadence_complete = coverage_complete and (
            not gaps or max(gaps) <= expected_interval * 2
        )
        all_pass = bool(coverage_samples) and all(
            sample["status"] == "PASS" for sample in coverage_samples
        )
        commits = {str(sample.get("git_commit", "")) for sample in coverage_samples}
        immutable_identity = (
            bool(coverage_samples)
            and len(commits) == 1
            and "" not in commits
            and all(sample.get("worktree_clean") is True for sample in coverage_samples)
        )
        if coverage_samples and not all_pass:
            status = "FAIL"
        elif coverage_complete and cadence_complete and immutable_identity:
            status = "PASS"
        else:
            status = "IN_PROGRESS"
        outcomes[label] = {
            "status": status,
            "elapsed_seconds": round(elapsed, 3),
            "required_seconds": seconds,
            "sample_count": len(coverage_samples),
            "all_samples_pass": all_pass,
            "cadence_complete": cadence_complete,
            "immutable_identity": immutable_identity,
            "latest_sample_age_seconds": round(latest_age, 3),
        }
    return {
        "evaluated_at": utc_now().isoformat(),
        "state_file": str(state),
        "windows": outcomes,
        "note": (
            "No observation window passes until real wall-clock coverage and cadence "
            "requirements are met."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("sample", "evaluate", "monitor"))
    parser.add_argument(
        "--state",
        type=Path,
        default=Path("build/observations/release-observations.jsonl"),
    )
    parser.add_argument(
        "--report", type=Path, default=Path("build/observations/window-status.json")
    )
    parser.add_argument("--endpoint", action="append", type=parse_endpoint)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--scope", default="local_compose")
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--duration-seconds", type=int, default=0)
    args = parser.parse_args()
    endpoints = args.endpoint or [parse_endpoint(value) for value in DEFAULT_ENDPOINTS]

    if args.command in {"sample", "monitor"}:
        deadline = (
            time.monotonic() + args.duration_seconds
            if args.command == "monitor"
            else time.monotonic()
        )
        while True:
            print(
                json.dumps(
                    append_sample(args.state, endpoints, args.timeout, args.scope),
                    indent=2,
                    sort_keys=True,
                )
            )
            if args.command == "sample" or time.monotonic() >= deadline:
                break
            time.sleep(args.interval_seconds)
    report = evaluate(args.state, args.interval_seconds)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
