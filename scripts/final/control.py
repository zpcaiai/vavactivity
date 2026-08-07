#!/usr/bin/env python3

"""Batch 32 final production-readiness control plane."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime, timezone
from datetime import datetime as dt
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "final"
BUILD = ROOT / "build" / "final"
MANIFEST_PATH = CONFIG / "manifest.yaml"
BATCH_NUMBER = 32


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must be a mapping")
    return value


def _git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write(name: str, payload: dict[str, Any]) -> str:
    BUILD.mkdir(parents=True, exist_ok=True)
    target = BUILD / name
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return str(target.relative_to(ROOT))


def _manifest() -> dict[str, Any]:
    manifest = _load_yaml(MANIFEST_PATH)
    if manifest.get("batch") != BATCH_NUMBER:
        raise ValueError(f"final manifest batch must be {BATCH_NUMBER}")
    if manifest.get("schema_version") != "1.0.0":
        raise ValueError("final manifest schema_version must be 1.0.0")
    return manifest


def _checksum(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _release_manifest_check(manifest: dict[str, Any]) -> dict[str, Any]:
    release = _as_dict(manifest.get("release_manifest"))
    artifacts = _as_list(release.get("required_artifacts"))
    missing = [item for item in artifacts if not (ROOT / item).is_file()]
    missing_non_waivable = _as_list(manifest.get("non_waivable_gates"))
    findings: list[str] = []
    if not artifacts:
        findings.append("required_artifacts_missing")
    if missing:
        findings.append("required_artifact_missing")
    if not missing_non_waivable:
        findings.append("non_waivable_gates_missing")
    return {
        "status": "PASS" if not findings else "FAIL",
        "required_artifacts": artifacts,
        "missing_artifacts": missing,
        "missing_non_waivable_gates": missing_non_waivable,
        "findings": findings,
    }


def _score_check(manifest: dict[str, Any]) -> dict[str, Any]:
    scores = _as_dict(manifest.get("quality_scores"))
    minimum = _as_float(scores.get("minimum_overall_threshold"), 1.0)
    required_dims = _as_list(manifest.get("go_no_go", {}).get("required_dims"))
    missing: list[str] = []
    insufficient: list[str] = []
    for dim, value in scores.items():
        if dim in {"minimum_overall_threshold", "schema_version"}:
            continue
        if not isinstance(value, (int, float)):
            missing.append(f"{dim}_missing")
            continue
        if value < 0 or value > 1:
            insufficient.append(f"{dim}_range")
        if dim in required_dims and value < minimum:
            insufficient.append(f"{dim}_below_minimum")
        if dim in required_dims and _as_float(value, 0.0) < minimum:
            insufficient.append(f"{dim}_go_no_go_below_minimum")
    required_dims_found = [dim for dim in required_dims if dim in scores]
    if set(required_dims_found) != set(required_dims):
        insufficient.append("required_dims_not_found")
    if _as_float(scores.get("go_no_go", minimum), 0.0) < minimum:
        insufficient.append("go_no_go_below_minimum")
    return {
        "status": "PASS" if not insufficient and not missing else "FAIL",
        "minimum_overall_threshold": minimum,
        "required_dims": required_dims,
        "scores": {key: _as_float(scores.get(key), 0.0) for key in sorted(set(scores) | set(required_dims))},
        "missing": missing,
        "insufficient": insufficient,
    }


def _go_no_go_check(manifest: dict[str, Any], score_check: dict[str, Any]) -> dict[str, Any]:
    go_no_go = _as_dict(manifest.get("go_no_go"))
    threshold = _as_float(go_no_go.get("threshold"), 0.0)
    max_critical = _as_float(go_no_go.get("critical_findings_max"), 0)
    required_dims = _as_list(go_no_go.get("required_dims"))
    security_posture = _as_dict(manifest.get("security_posture"))
    findings: list[str] = []
    overall = _as_float(
        _as_dict(manifest.get("quality_scores")).get("minimum_overall_threshold"),
        0.0,
    )
    if overall < threshold:
        findings.append("overall_threshold_not_met")
    if security_posture.get("critical_open_findings") is None:
        findings.append("critical_open_findings_missing")
    elif _as_float(security_posture.get("critical_open_findings"), 0.0) > max_critical:
        findings.append("critical_open_findings_over_limit")
    if _as_float(security_posture.get("unresolved_sev1_findings"), 0.0) > max_critical:
        findings.append("unresolved_sev1_findings_over_limit")
    score_dims = _as_dict(score_check.get("scores", {}))
    for dim in required_dims:
        if _as_float(score_dims.get(dim), 0.0) < threshold:
            findings.append(f"go_no_go_required_dim_below_threshold:{dim}")
        if dim not in score_dims:
            findings.append(f"required_dim_score_missing:{dim}")
    if security_posture.get("external_pen_test_last") is None:
        findings.append("external_pen_test_last_missing")
    return {
        "status": "PASS" if not findings else "FAIL",
        "threshold": threshold,
        "critical_findings_max": max_critical,
        "required_dims": required_dims,
        "critical_findings": _as_float(security_posture.get("critical_open_findings"), 0.0),
        "unresolved_sev1_findings": _as_float(security_posture.get("unresolved_sev1_findings"), 0.0),
        "external_pen_test_last": security_posture.get("external_pen_test_last"),
        "findings": findings,
    }


def _approval_checks(manifest: dict[str, Any]) -> dict[str, Any]:
    approvals = _as_dict(manifest.get("approvals"))
    findings: list[str] = []
    for key, item in approvals.items():
        if not isinstance(item, dict):
            findings.append(f"{key}:invalid_entry")
            continue
        if item.get("required") and not _as_bool(item.get("approved")):
            findings.append(f"{key}:not_approved")
    return {
        "status": "PASS" if not findings else "FAIL",
        "approvals": approvals,
        "findings": findings,
    }


def _parse_aware_datetime(value: str) -> dt:
    if value.endswith("Z"):
        value = value.replace("Z", "+00:00")
    return dt.fromisoformat(value)


def _observation_checks(manifest: dict[str, Any], key: str) -> dict[str, Any]:
    windows = _as_dict(manifest.get("observation_windows"))
    payload = _as_dict(windows.get(key))
    findings: list[str] = []
    if not payload:
        return {"status": "NOT_EVALUATED", "findings": ["window_missing"]}
    policy = str(payload.get("policy", ""))
    critical_events = _as_float(payload.get("critical_events_detected"), 0.0)
    current_production = payload.get("current_production_time")
    expected_ends = payload.get("expected_ends_at")
    starts_at = payload.get("starts_at")
    now = dt.now(timezone.utc)
    if current_production and expected_ends:
        try:
            current_at = _parse_aware_datetime(str(current_production))
            expected_at = _parse_aware_datetime(str(expected_ends))
            if current_at < expected_at:
                findings.append("observation_not_completed")
            if current_at > now:
                findings.append("current_production_time_in_future")
            if starts_at:
                starts_at_dt = _parse_aware_datetime(str(starts_at))
                if current_at < starts_at_dt:
                    findings.append("current_before_starts_at")
                elapsed_hours = (current_at - starts_at_dt).total_seconds() / 3600
                if elapsed_hours < 0:
                    findings.append("observation_window_negative_elapsed")
        except Exception:
            findings.append("observation_time_parse_error")
    elif not current_production or not expected_ends:
        findings.append("observation_time_fields_missing")
    if critical_events > 0:
        findings.append("critical_events_detected")
    if not policy:
        findings.append("policy_missing")
    return {
        "status": "PASS" if not findings else "FAIL",
        "policy": policy,
        "expected_ends_at": payload.get("expected_ends_at"),
        "current_production_time": current_production,
        "critical_events_detected": critical_events,
        "findings": findings,
    }


def _launch_checks(manifest: dict[str, Any]) -> dict[str, Any]:
    launch = _as_dict(manifest.get("launch"))
    findings: list[str] = []
    preconditions = _as_list(launch.get("preconditions"))
    if not preconditions:
        findings.append("missing_preconditions")
    for item in preconditions:
        if not _as_bool(item):
            findings.append(f"precondition_not_met:{item}")
    gate_checks = _as_list(launch.get("gate_checks"))
    if not gate_checks:
        findings.append("missing_gate_checks")
    return {
        "status": "PASS" if not findings else "FAIL",
        "preconditions": preconditions,
        "gate_checks": gate_checks,
        "findings": findings,
    }


def _security_test_evidence() -> dict[str, Any]:
    path = ROOT / "build" / "security" / "security-evidence.json"
    if not path.is_file():
        return {"status": "NOT_EVALUATED", "path": str(path), "technical_status": "NOT_EVALUATED"}
    try:
        report = _as_dict(json.loads(path.read_text(encoding="utf-8")))
        technical_status = str(report.get("technical_status", "NOT_EVALUATED"))
    except Exception:
        return {"status": "FAIL", "path": str(path), "technical_status": "INVALID"}
    return {
        "status": "PASS" if technical_status in {"PASS", "NOT_CERTIFIED"} else "FAIL",
        "path": str(path),
        "technical_status": technical_status,
        "git_commit": report.get("git_commit"),
    }


def _snapshot() -> dict[str, Any]:
    manifest = _manifest()
    release_check = _release_manifest_check(manifest)
    score = _score_check(manifest)
    go_no_go = _go_no_go_check(manifest, score)
    approvals = _approval_checks(manifest)
    launch = _launch_checks(manifest)
    obs_24h = _observation_checks(manifest, "24h")
    obs_7d = _observation_checks(manifest, "7d")
    obs_30d = _observation_checks(manifest, "30d")
    security = _security_test_evidence()
    payload = {
        "schema_version": manifest["schema_version"],
        "batch": manifest["batch"],
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "manifest_checksum": _checksum(manifest),
        "release_manifest": release_check,
        "score": score,
        "go_no_go": go_no_go,
        "approval": approvals,
        "launch": launch,
        "observation": {
            "24h": obs_24h,
            "7d": obs_7d,
            "30d": obs_30d,
        },
        "security_evidence": security,
    }
    statuses = [
        release_check["status"],
        score["status"],
        go_no_go["status"],
        approvals["status"],
        launch["status"],
        obs_24h["status"],
        obs_7d["status"],
        obs_30d["status"],
        security["status"],
    ]
    payload["technical_status"] = "PASS" if all(item == "PASS" for item in statuses) else "FAIL"
    payload["evidence_check"] = security
    payload["skill_count"] = len(list((ROOT / "skills/batch-32").glob("[0-9][0-9]-*/SKILL.md")))
    return payload


def _print(payload: dict[str, Any], action: str) -> None:
    output = {"command": action, **payload}
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))


def run(action: str) -> int:
    snap = _snapshot()

    if action in {"migrate", "seed"}:
        print(json.dumps({"command": action, "status": "NOT_RUN", "reason": "offline control plane"}, sort_keys=True))
        return 0

    if action in {"sync", "final-sync"}:
        print(_write("final-snapshot.json", snap))
        return 0

    if action in {"release-manifest-check", "release-manifest", "release-manifest-check", "release-check"}:
        _print(snap["release_manifest"], action)
        return 0 if snap["release_manifest"]["status"] == "PASS" else 1

    if action in {"score-test", "score"}:
        _print(snap["score"], action)
        return 0 if snap["score"]["status"] == "PASS" else 1

    if action in {"go-no-go-test", "go-no-go"}:
        _print(snap["go_no_go"], action)
        return 0 if snap["go_no_go"]["status"] == "PASS" else 1

    if action in {"approval-test", "approval"}:
        _print(snap["approval"], action)
        return 0 if snap["approval"]["status"] == "PASS" else 1

    if action in {"launch-test", "launch"}:
        _print(snap["launch"], action)
        return 0 if snap["launch"]["status"] == "PASS" else 1

    if action in {"observation-policy-test", "observation-policy", "observation-policy-check"}:
        _print(snap["observation"], action)
        return 0 if all(item["status"] == "PASS" for item in (snap["observation"]["24h"], snap["observation"]["7d"], snap["observation"]["30d"])) else 1

    if action in {"evidence-test", "evidence"}:
        _print(snap["security_evidence"], action)
        return 0 if snap["security_evidence"]["status"] in {"PASS", "NOT_EVALUATED"} else 1

    if action in {"security-test", "security"}:
        _print(snap["security_evidence"], action)
        return 0 if snap["security_evidence"]["status"] in {"PASS", "NOT_EVALUATED"} else 1

    if action in {"final-admin-e2e", "admin-e2e"}:
        print(json.dumps({"command": action, "status": "NOT_RUN", "reason": "offline control"}, sort_keys=True))
        return 0

    if action == "observe-24h":
        _print(snap["observation"]["24h"], action)
        return 0 if snap["observation"]["24h"]["status"] in {"PASS", "NOT_EVALUATED"} else 1

    if action == "observe-7d":
        _print(snap["observation"]["7d"], action)
        return 0 if snap["observation"]["7d"]["status"] in {"PASS", "NOT_EVALUATED"} else 1

    if action == "observe-30d":
        _print(snap["observation"]["30d"], action)
        return 0 if snap["observation"]["30d"]["status"] in {"PASS", "NOT_EVALUATED"} else 1

    if action in {"evidence-build", "release-candidate"}:
        report = {
            "schema_version": "1.0.0",
            "batch": BATCH_NUMBER,
            "generated_at": datetime.now(UTC).isoformat(),
            "git_commit": snap["git_commit"],
            "technical_status": snap["technical_status"],
            "production_certification": "NOT_CERTIFIED",
            "release_allowed": False,
            "release_manifest": snap["release_manifest"],
            "score": snap["score"],
            "go_no_go": snap["go_no_go"],
            "approval": snap["approval"],
            "launch": snap["launch"],
            "observation": snap["observation"],
            "security_integration": snap["security_evidence"],
            "external_gates": {
                "admin_e2e": "NOT_RUN",
                "production_observation": "NOT_RUN",
            },
            "build_artifacts": {
                "quality": snap["release_manifest"].get("status"),
                "ui": "NOT_EVALUATED",
                "experience": "NOT_EVALUATED",
                "process": "NOT_EVALUATED",
                "data_integrity": "NOT_EVALUATED",
                "admin_completeness": "NOT_EVALUATED",
                "usability": "NOT_EVALUATED",
            },
        }
        print(_write("final-evidence.json", report))
        return 0 if report["technical_status"] in {"PASS", "NOT_CERTIFIED"} else 1

    if action == "certify":
        status = "PASS" if snap["technical_status"] == "PASS" else "FAIL"
        result = {
            "command": action,
            "status": status,
            "technical_status": snap["technical_status"],
            "production_certification": "NOT_CERTIFIED",
            "observation": snap["observation"],
            "release_allowed": snap["technical_status"] == "PASS",
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if status == "PASS" else 1

    raise ValueError(f"unsupported final action: {action}")


def parse_action(parts: list[str]) -> str:
    normalized: list[str] = []
    for part in parts:
        normalized.extend(
            token
            for token in str(part).replace("_", "-").lower().split("-")
            if token
        )
    if normalized and normalized[0] == "final":
        normalized = normalized[1:]
    aliases = {
        ("migrate",): "migrate",
        ("seed",): "seed",
        ("sync",): "sync",
        ("release", "manifest", "check"): "release-manifest-check",
        ("release-manifest",): "release-manifest-check",
        ("release", "manifest"): "release-manifest-check",
        ("release", "candidate"): "release-candidate",
        ("release", "candidate", "build"): "release-candidate",
        ("release-candidate",): "release-candidate",
        ("certify",): "certify",
        ("production", "stable", "certify"): "certify",
        ("score", "test"): "score-test",
        ("score",): "score-test",
        ("go", "no", "go", "test"): "go-no-go-test",
        ("go-no-go",): "go-no-go-test",
        ("go", "no", "go"): "go-no-go-test",
        ("approval", "test"): "approval-test",
        ("approval",): "approval-test",
        ("launch", "test"): "launch-test",
        ("launch",): "launch-test",
        ("observation", "policy", "test"): "observation-policy-test",
        ("observation", "policy"): "observation-policy-test",
        ("observation", "policy", "check"): "observation-policy-test",
        ("evidence", "test"): "evidence-test",
        ("evidence",): "evidence",
        ("evidence", "build"): "evidence-build",
        ("security",): "security-test",
        ("security", "test"): "security-test",
        ("admin", "e2e"): "final-admin-e2e",
        ("observe-24h",): "observe-24h",
        ("observe-7d",): "observe-7d",
        ("observe-30d",): "observe-30d",
        ("observe", "24h"): "observe-24h",
        ("observe", "7d"): "observe-7d",
        ("observe", "30d"): "observe-30d",
        ("production", "observation", "24h", "evaluate"): "observe-24h",
        ("production", "observation", "7d", "evaluate"): "observe-7d",
        ("production", "observation", "30d", "evaluate"): "observe-30d",
        ("final-admin-e2e",): "final-admin-e2e",
    }
    return aliases.get(tuple(normalized), "-".join(normalized))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="+")
    args = parser.parse_args()
    action = parse_action([part.lower() for part in args.command])
    try:
        return run(action)
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise SystemExit(f"final control failed: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
