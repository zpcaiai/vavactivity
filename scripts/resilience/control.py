#!/usr/bin/env python3

"""Batch 31 resilience control plane for offline reliability gate evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "resilience"
BUILD = ROOT / "build" / "resilience"
MANIFEST_PATH = CONFIG / "manifest.yaml"
BATCH_NUMBER = 31


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "t", "y"}
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
        raise ValueError(f"resilience manifest batch must be {BATCH_NUMBER}")
    if manifest.get("schema_version") != "1.0.0":
        raise ValueError("resilience manifest schema_version must be 1.0.0")
    return manifest


def _checksum(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _slo_checks(manifest: dict[str, Any]) -> dict[str, Any]:
    findings: list[str] = []
    items = []
    for item in _as_list(manifest.get("slos")):
        code = str(item.get("code", "SLO-UNKNOWN"))
        objective = _as_float(item.get("objective"), 0.0)
        window_minutes = _as_int(item.get("window_minutes"), 0)
        window_hours = _as_float(item.get("window_hours"), 0.0)
        burn = _as_float(item.get("burn_rate_threshold"), 0.0)
        category = str(item.get("category", "unknown"))
        if objective <= 0 or objective > 1:
            findings.append(f"{code}:objective_range")
        if window_minutes <= 0:
            findings.append(f"{code}:window_minutes")
        if window_hours <= 0:
            findings.append(f"{code}:window_hours")
        if burn <= 0:
            findings.append(f"{code}:burn_rate_threshold")
        items.append(
            {
                "code": code,
                "objective": objective,
                "window_minutes": window_minutes,
                "window_hours": window_hours,
                "burn_rate_threshold": burn,
                "category": category,
                "status": "PASS" if code.startswith("SLO-") else "UNKNOWN",
            }
        )
    status = "PASS" if not findings else "FAIL"
    return {
        "status": status,
        "count": len(items),
        "failures": findings,
        "items": items,
    }


def _error_budget_tests(manifest: dict[str, Any]) -> dict[str, Any]:
    findings: list[str] = []
    budgets = []
    for item in _as_list(manifest.get("error_budgets")):
        code = str(item.get("code", "ERR-UNKNOWN"))
        observed = _as_float(item.get("observed_error_rate"), 0.0)
        target = _as_float(item.get("target_error_rate"), 1.0)
        burn = _as_float(item.get("burn_rate"), 0.0)
        if observed > target:
            findings.append(f"{code}:observed_exceeds_target")
        if burn < 0 or burn > 1:
            findings.append(f"{code}:burn_rate_out_of_range")
        budgets.append(
            {
                "code": code,
                "observed_error_rate": observed,
                "target_error_rate": target,
                "burn_rate": burn,
                "budget_ms": _as_float(item.get("budget_ms"), 0.0),
                "status": "PASS" if (observed <= target and 0 <= burn <= 1) else "FAIL",
            }
        )
    return {
        "status": "PASS" if not findings else "FAIL",
        "count": len(budgets),
        "failures": findings,
        "items": budgets,
    }


def _observability_checks(manifest: dict[str, Any]) -> dict[str, Any]:
    obs = _as_dict(manifest.get("observability"))
    logs = _as_dict(obs.get("logs"))
    metrics = _as_dict(obs.get("metrics"))
    checks: list[str] = []

    required_fields = _as_list(logs.get("required_fields"))
    pii_fields_present = _as_list(logs.get("pii_fields_present"))
    if set(required_fields) != {"trace_id", "event_name", "tenant_id", "severity"}:
        checks.append("observability_missing_required_logs")
    if pii_fields_present:
        checks.append("pii_fields_present")

    expected_coverage_ratio = _as_float(metrics.get("expected_coverage_ratio"), 0.0)
    observed_coverage_ratio = _as_float(metrics.get("observed_coverage_ratio"), 0.0)
    if observed_coverage_ratio + 1e-9 < expected_coverage_ratio:
        checks.append("metric_coverage_under_threshold")

    redacted_ratio = _as_float(metrics.get("sensitive_data_redacted_ratio"), 0.0)
    if redacted_ratio < 1.0:
        checks.append("sensitive_data_not_fully_redacted")

    traces_min = _as_float(metrics.get("traces_per_minute_min"), 0.0)
    traces_observed = _as_float(metrics.get("traces_per_minute_observed"), 0.0)
    if traces_observed <= 0 and traces_min > 0:
        checks.append("traces_per_minute_observed_missing")
        traces_observed = 0.0
    if traces_min > 0 and traces_observed < traces_min:
        checks.append("traces_per_minute_below_minimum")

    canary = _as_dict(obs.get("canary"))
    tests = _as_list(canary.get("tests"))
    critical_tests = [item for item in tests if _as_bool(item.get("critical"))]
    uncovered = [item for item in critical_tests if not _as_bool(item.get("covered"))]
    if uncovered:
        checks.append(f"canary_uncovered:{len(uncovered)}")

    return {
        "status": "PASS" if not checks else "FAIL",
        "findings": checks,
        "logs": {
            "required_fields": required_fields,
            "pii_fields_present": pii_fields_present,
        },
        "metrics": {
            "expected_coverage_ratio": expected_coverage_ratio,
            "observed_coverage_ratio": observed_coverage_ratio,
            "sensitive_data_redacted_ratio": redacted_ratio,
            "traces_per_minute_min": traces_min,
            "traces_per_minute_observed": traces_observed,
        },
        "canary": {
            "enabled": _as_bool(canary.get("enabled")),
            "test_count": len(tests),
            "critical_test_count": len(critical_tests),
        },
    }


def _synthetic_monitor_checks(manifest: dict[str, Any]) -> dict[str, Any]:
    checks: list[str] = []
    monitor = _as_dict(manifest.get("synthetic_monitors"))
    tests = _as_list(monitor.get("tests"))
    if not _as_bool(monitor.get("enabled")):
        checks.append("synthetic_disabled")
    cadence = _as_int(monitor.get("cadence_minutes"), 0)
    if cadence <= 0 or cadence > 60:
        checks.append("invalid_cadence")
    critical_tests = [item for item in tests if _as_bool(item.get("critical"))]
    critical_not_covered = sum(1 for item in critical_tests if not (
        _as_bool(item.get("covered")) or str(item.get("status", "")).lower() == "passed"
    ))

    if critical_not_covered:
        checks.append(f"critical_synthetic_not_covered:{critical_not_covered}")
    return {
        "status": "PASS" if not checks else "FAIL",
        "enabled": _as_bool(monitor.get("enabled")),
        "cadence_minutes": cadence,
        "tests": len(tests),
        "critical_not_covered": critical_not_covered,
        "failures": checks,
    }


def _ha_api(manifest: dict[str, Any]) -> dict[str, Any]:
    api = _as_dict(manifest.get("ha_checks", {}).get("api"))
    findings: list[str] = []
    readiness = _as_float(api.get("readiness_time_seconds"), 0.0)
    failover = _as_float(api.get("failover_time_seconds"), 0.0)
    req_readiness = _as_float(api.get("required_readiness_threshold_seconds"), 0.0)
    req_failover = _as_float(api.get("required_failover_threshold_seconds"), 0.0)
    if readiness <= 0:
        findings.append("api_readiness_missing")
    if failover <= 0:
        findings.append("api_failover_missing")
    if readiness > req_readiness > 0:
        findings.append("api_readiness_exceeds_threshold")
    if failover > req_failover > 0:
        findings.append("api_failover_exceeds_threshold")
    return {
        "status": "PASS" if not findings else "FAIL",
        "readiness_time_seconds": readiness,
        "failover_time_seconds": failover,
        "required_readiness_threshold_seconds": req_readiness,
        "required_failover_threshold_seconds": req_failover,
        "findings": findings,
    }


def _ha_database(manifest: dict[str, Any]) -> dict[str, Any]:
    db = _as_dict(manifest.get("ha_checks", {}).get("database"))
    findings: list[str] = []
    failover = _as_float(db.get("failover_time_seconds"), 0.0)
    wal = _as_float(db.get("wal_replay_seconds"), 0.0)
    req_failover = _as_float(db.get("required_failover_threshold_seconds"), 0.0)
    raw_time = _as_float(db.get("read_after_write_time_ms"), 0.0)
    req_raw = _as_float(db.get("required_read_after_write_threshold_ms"), 0.0)
    if failover <= 0:
        findings.append("database_failover_missing")
    if wal <= 0:
        findings.append("database_wal_replay_missing")
    if failover > req_failover > 0:
        findings.append("database_failover_exceeds_threshold")
    if raw_time > req_raw > 0:
        findings.append("database_read_after_write_exceeds_threshold")
    return {
        "status": "PASS" if not findings else "FAIL",
        "failover_time_seconds": failover,
        "wal_replay_seconds": wal,
        "read_after_write_time_ms": raw_time,
        "required_read_after_write_threshold_ms": req_raw,
        "findings": findings,
    }


def _ha_redis_worker(manifest: dict[str, Any]) -> dict[str, Any]:
    worker = _as_dict(manifest.get("ha_checks", {}).get("redis_worker"))
    findings: list[str] = []
    failover = _as_float(worker.get("failover_time_seconds"), 0.0)
    req_failover = _as_float(worker.get("required_failover_threshold_seconds"), 0.0)
    queue_lag = _as_float(worker.get("queue_replay_lag_seconds"), 0.0)
    req_queue = _as_float(worker.get("required_replay_lag_seconds"), 0.0)
    queue_recover = _as_float(worker.get("queue_recover_time_seconds"), 0.0)
    if queue_recover <= 0:
        findings.append("queue_recover_missing")
    if failover <= 0:
        findings.append("redis_failover_missing")
    if failover > req_failover > 0:
        findings.append("redis_failover_exceeds_threshold")
    if queue_lag > req_queue > 0:
        findings.append("redis_queue_replay_lag_exceeds_threshold")
    return {
        "status": "PASS" if not findings else "FAIL",
        "failover_time_seconds": failover,
        "queue_recover_time_seconds": queue_recover,
        "queue_replay_lag_seconds": queue_lag,
        "findings": findings,
    }


def _provider_resilience(manifest: dict[str, Any]) -> dict[str, Any]:
    providers = _as_list(manifest.get("provider_resilience", {}).get("services"))
    findings: list[str] = []
    details = []
    for item in providers:
        provider = str(item.get("provider", "unknown"))
        provider_findings: list[str] = []
        timeout = _as_float(item.get("timeout_seconds"), 0.0)
        retry = _as_int(item.get("retry_budget"), 0)
        failure_ratio = _as_float(item.get("circuit_breaker_failure_ratio"), 0.0)
        window = _as_int(item.get("circuit_breaker_window"), 0)
        fallback = _as_bool(item.get("fallback_enabled"))
        if timeout <= 0:
            provider_findings.append("timeout_invalid")
            findings.append(f"{provider}:timeout_invalid")
        if timeout > 5:
            provider_findings.append("timeout_too_long")
            findings.append(f"{provider}:timeout_too_long")
        if retry <= 0:
            provider_findings.append("retry_budget_missing")
            findings.append(f"{provider}:retry_budget_missing")
        if failure_ratio < 0 or failure_ratio > 1:
            provider_findings.append("failure_ratio_invalid")
            findings.append(f"{provider}:failure_ratio_invalid")
        if failure_ratio > 0.3 and not fallback:
            provider_findings.append("fallback_required_for_ratio")
            findings.append(f"{provider}:fallback_required_for_ratio")
        if window <= 0:
            provider_findings.append("circuit_breaker_window_invalid")
            findings.append(f"{provider}:circuit_breaker_window_invalid")
        details.append(
            {
                "provider": provider,
                "timeout_seconds": timeout,
                "retry_budget": retry,
                "circuit_breaker_failure_ratio": failure_ratio,
                "circuit_breaker_window": window,
                "fallback_enabled": fallback,
                "findings": provider_findings,
                "status": "PASS" if not provider_findings else "FAIL",
            }
        )
    return {
        "status": "PASS" if not findings else "FAIL",
        "provider_count": len(providers),
        "failure_count": sum(1 for item in details if item["status"] == "FAIL"),
        "providers": details,
        "findings": findings,
    }


def _degradation_checks(manifest: dict[str, Any]) -> dict[str, Any]:
    expected = _as_dict(manifest.get("degradation", {}).get("expected_behavior"))
    tolerance = _as_dict(manifest.get("degradation", {}).get("tolerance"))
    findings: list[str] = []
    delay_ms = _as_int(expected.get("quality_graceful_delay_ms"), 0)
    reduced_set = _as_bool(expected.get("reduced_feature_set"))
    queue_retries_cap = _as_int(expected.get("queue_retries_cap"), 0)

    max_blackout = _as_float(tolerance.get("max_feature_blackout_ratio"), 0.0)
    max_latency_inc = _as_float(tolerance.get("max_latency_increase_ratio"), 0.0)
    min_throughput = _as_float(tolerance.get("min_user_task_throughput_ratio"), 0.0)

    if delay_ms <= 0:
        findings.append("quality_graceful_delay_missing")
    if not reduced_set:
        findings.append("reduced_feature_set_not_enabled")
    if queue_retries_cap < 3:
        findings.append("queue_retries_cap_too_low")
    if max_blackout > 0.25:
        findings.append("max_feature_blackout_ratio_too_high")
    if max_latency_inc > 2.0:
        findings.append("max_latency_increase_ratio_too_high")
    if min_throughput < 0.8:
        findings.append("user_throughput_ratio_too_low")

    return {
        "status": "PASS" if not findings else "FAIL",
        "quality_graceful_delay_ms": delay_ms,
        "reduced_feature_set": reduced_set,
        "queue_retries_cap": queue_retries_cap,
        "max_feature_blackout_ratio": max_blackout,
        "max_latency_increase_ratio": max_latency_inc,
        "min_user_task_throughput_ratio": min_throughput,
        "findings": findings,
    }


def _chaos_checks(manifest: dict[str, Any]) -> dict[str, Any]:
    chaos = _as_dict(manifest.get("chaos"))
    tests = _as_list(chaos.get("tests"))
    findings: list[str] = []
    if not _as_bool(chaos.get("allowed")):
        findings.append("chaos_not_allowed")
    if not _as_bool(chaos.get("approved")):
        findings.append("chaos_not_approved")
    max_duration = _as_int(chaos.get("max_duration_seconds"), 0)
    if max_duration <= 0:
        findings.append("max_duration_invalid")
    passed_tests = [item for item in tests if str(item.get("status", "")).lower() == "passed"]
    failed_tests = [item for item in tests if str(item.get("status", "")).lower() != "passed"]
    if failed_tests:
        findings.append(f"chaos_tests_failed:{len(failed_tests)}")
    return {
        "status": "PASS" if not findings else "FAIL",
        "allowed": _as_bool(chaos.get("allowed")),
        "approved": _as_bool(chaos.get("approved")),
        "max_duration_seconds": max_duration,
        "tests": {
            "total": len(tests),
            "passed": len(passed_tests),
            "failed": len(failed_tests),
            "items": tests,
        },
        "findings": findings,
    }


def _backup_restore_checks(manifest: dict[str, Any]) -> dict[str, Any]:
    backup = _as_dict(manifest.get("backup_restore"))
    findings: list[str] = []
    for key in ("backup_window_minutes", "restore_time_minutes"):
        if not _as_float(backup.get(key), 0.0):
            findings.append(f"{key}_invalid")
    if _as_bool(backup.get("restore_tested")) is False:
        findings.append("restore_not_tested")
    if _as_bool(backup.get("consistency_checks_passed")) is False:
        findings.append("consistency_checks_not_passed")
    return {
        "status": "PASS" if not findings else "FAIL",
        "restore_tested": _as_bool(backup.get("restore_tested")),
        "consistency_checks_passed": _as_bool(backup.get("consistency_checks_passed")),
        "backup_window_minutes": _as_float(backup.get("backup_window_minutes"), 0.0),
        "restore_time_minutes": _as_float(backup.get("restore_time_minutes"), 0.0),
        "findings": findings,
    }


def _disaster_recovery_checks(manifest: dict[str, Any]) -> dict[str, Any]:
    dr = _as_dict(manifest.get("disaster_recovery"))
    findings: list[str] = []
    if _as_bool(dr.get("exercise_executed")) is False:
        findings.append("dr_exercise_not_executed")
    if _as_float(dr.get("rto_minutes"), 0.0) > 180:
        findings.append("rto_exceeds_target")
    if _as_float(dr.get("rpo_minutes"), 0.0) > 10:
        findings.append("rpo_exceeds_target")
    if _as_bool(dr.get("data_integrity_verified")) is False:
        findings.append("data_integrity_not_verified")
    return {
        "status": "PASS" if not findings else "FAIL",
        "exercise_executed": _as_bool(dr.get("exercise_executed")),
        "rto_minutes": _as_float(dr.get("rto_minutes"), 0.0),
        "rpo_minutes": _as_float(dr.get("rpo_minutes"), 0.0),
        "data_integrity_verified": _as_bool(dr.get("data_integrity_verified")),
        "findings": findings,
    }


def _incident_management_checks(manifest: dict[str, Any]) -> dict[str, Any]:
    incident = _as_dict(manifest.get("incident_management"))
    findings: list[str] = []
    if _as_bool(incident.get("requires_postmortem_sev0")) is False:
        findings.append("sev0_postmortem_required")
    if _as_bool(incident.get("requires_postmortem_sev1")) is False:
        findings.append("sev1_postmortem_required")
    examples = _as_list(incident.get("postmortem_examples"))
    severity_required = {"sev0", "sev1"}
    completed = {str(item.get("severity")) for item in examples if _as_bool(item.get("completed"))}
    missing = sorted(severity_required - completed)
    if missing:
        findings.append(f"missing_postmortem:{','.join(missing)}")
    return {
        "status": "PASS" if not findings else "FAIL",
        "requires_postmortem_sev0": _as_bool(incident.get("requires_postmortem_sev0")),
        "requires_postmortem_sev1": _as_bool(incident.get("requires_postmortem_sev1")),
        "postmortem_examples": examples,
        "findings": findings,
    }


def _resilience_test_checks(manifest: dict[str, Any]) -> dict[str, Any]:
    resilience_tests = _as_dict(manifest.get("resilience_tests"))
    status_map = _as_dict(resilience_tests.get("chaos_exit_codes"))
    findings: list[str] = []
    for name, value in status_map.items():
        if _as_int(value, 1) != 0:
            findings.append(f"chaos_exit_{name}_non_zero")
    return {
        "status": "PASS" if not findings else "FAIL",
        "chaos_exit_codes": status_map,
        "findings": findings,
    }


def _security_checks(manifest: dict[str, Any]) -> dict[str, Any]:
    security = _as_dict(manifest.get("security"))
    findings: list[str] = []
    if _as_bool(security.get("auth_bypass_detected")):
        findings.append("auth_bypass_detected")
    if _as_int(security.get("critical_findings"), 0) > 0:
        findings.append("critical_findings")
    if _as_int(security.get("open_incidents"), 0) > 0:
        findings.append("open_incidents")
    if _as_int(security.get("secrets_in_logs_detected"), 0) > 0:
        findings.append("secrets_in_logs")
    return {
        "status": "PASS" if not findings else "FAIL",
        "open_incidents": _as_int(security.get("open_incidents"), 0),
        "critical_findings": _as_int(security.get("critical_findings"), 0),
        "auth_bypass_detected": _as_bool(security.get("auth_bypass_detected")),
        "secrets_in_logs_detected": _as_int(security.get("secrets_in_logs_detected"), 0),
        "findings": findings,
    }


def _snapshot() -> dict[str, Any]:
    manifest = _manifest()
    payload = {
        "schema_version": "1.0.0",
        "batch": manifest["batch"],
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "manifest_checksum": _checksum(manifest),
        "slo_checks": _slo_checks(manifest),
        "error_budget_tests": _error_budget_tests(manifest),
        "observability_tests": _observability_checks(manifest),
        "synthetic_monitor_tests": _synthetic_monitor_checks(manifest),
        "api_ha_tests": _ha_api(manifest),
        "database_ha_tests": _ha_database(manifest),
        "redis_worker_ha_tests": _ha_redis_worker(manifest),
        "provider_resilience_tests": _provider_resilience(manifest),
        "degradation_tests": _degradation_checks(manifest),
        "chaos_tests": _chaos_checks(manifest),
        "backup_restore_tests": _backup_restore_checks(manifest),
        "disaster_recovery_tests": _disaster_recovery_checks(manifest),
        "incident_management_tests": _incident_management_checks(manifest),
        "resilience_test_status": _resilience_test_checks(manifest),
        "security_integration_tests": _security_checks(manifest),
    }
    hard_failures = [
        payload["slo_checks"]["status"],
        payload["error_budget_tests"]["status"],
        payload["observability_tests"]["status"],
        payload["synthetic_monitor_tests"]["status"],
        payload["api_ha_tests"]["status"],
        payload["database_ha_tests"]["status"],
        payload["redis_worker_ha_tests"]["status"],
        payload["provider_resilience_tests"]["status"],
        payload["degradation_tests"]["status"],
        payload["chaos_tests"]["status"],
        payload["incident_management_tests"]["status"],
        payload["security_integration_tests"]["status"],
    ]
    payload["technical_status"] = "PASS" if all(item == "PASS" for item in hard_failures) else "FAIL"
    payload["skill_count"] = len(list((ROOT / "skills/batch-31").glob("[0-9][0-9]-*/SKILL.md")))
    return payload


def _print(payload: dict[str, Any], action: str) -> None:
    output = {"command": action, **payload}
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))


def run(action: str) -> int:
    snap = _snapshot()
    if action in {"migrate", "seed"}:
        print(json.dumps({"command": action, "status": "NOT_RUN", "reason": "offline control plane"}, sort_keys=True))
        return 0

    if action in {"sync", "resilience-sync"}:
        print(_write("resilience-snapshot.json", snap))
        return 0

    if action == "slo-check":
        _print(snap["slo_checks"], action)
        return 0 if snap["slo_checks"]["status"] == "PASS" else 1

    if action == "error-budget-test":
        _print(snap["error_budget_tests"], action)
        return 0 if snap["error_budget_tests"]["status"] == "PASS" else 1

    if action == "observability-test":
        _print(snap["observability_tests"], action)
        return 0 if snap["observability_tests"]["status"] == "PASS" else 1

    if action == "synthetic-monitor-test":
        _print(snap["synthetic_monitor_tests"], action)
        return 0 if snap["synthetic_monitor_tests"]["status"] == "PASS" else 1

    if action == "api-ha-test":
        _print(snap["api_ha_tests"], action)
        return 0 if snap["api_ha_tests"]["status"] == "PASS" else 1

    if action == "database-ha-test":
        _print(snap["database_ha_tests"], action)
        return 0 if snap["database_ha_tests"]["status"] == "PASS" else 1

    if action == "redis-worker-ha-test":
        _print(snap["redis_worker_ha_tests"], action)
        return 0 if snap["redis_worker_ha_tests"]["status"] == "PASS" else 1

    if action == "provider-resilience-test":
        _print(snap["provider_resilience_tests"], action)
        return 0 if snap["provider_resilience_tests"]["status"] == "PASS" else 1

    if action == "degradation-test":
        _print(snap["degradation_tests"], action)
        return 0 if snap["degradation_tests"]["status"] == "PASS" else 1

    if action in {"resilience-security-test", "security-test"}:
        _print(snap["security_integration_tests"], action)
        return 0 if snap["security_integration_tests"]["status"] == "PASS" else 1

    if action == "chaos-test":
        _print(snap["chaos_tests"], action)
        return 0 if snap["chaos_tests"]["status"] == "PASS" else 1

    if action == "backup-restore-test":
        _print(snap["backup_restore_tests"], action)
        return 0 if snap["backup_restore_tests"]["status"] == "PASS" else 1

    if action == "dr-game-day-test":
        _print(snap["disaster_recovery_tests"], action)
        return 0 if snap["disaster_recovery_tests"]["status"] == "PASS" else 1

    if action == "incident-management-test":
        _print(snap["incident_management_tests"], action)
        return 0 if snap["incident_management_tests"]["status"] == "PASS" else 1

    if action in {"resilience-admin-e2e", "admin-e2e"}:
        print(json.dumps({"command": action, "status": "NOT_RUN", "reason": "offline control"}, sort_keys=True))
        return 0

    if action in {"evidence", "evidence-build"}:
        report = {
            "schema_version": "1.0.0",
            "batch": BATCH_NUMBER,
            "generated_at": datetime.now(UTC).isoformat(),
            "git_commit": snap["git_commit"],
            "technical_status": snap["technical_status"],
            "production_certification": "NOT_CERTIFIED",
            "release_allowed": False,
            "slo": snap["slo_checks"],
            "error_budget": snap["error_budget_tests"],
            "observability": snap["observability_tests"],
            "synthetic_monitor": snap["synthetic_monitor_tests"],
            "ha": {
                "api": snap["api_ha_tests"],
                "database": snap["database_ha_tests"],
                "redis_worker": snap["redis_worker_ha_tests"],
            },
            "provider_resilience": snap["provider_resilience_tests"],
            "degradation": snap["degradation_tests"],
            "chaos": snap["chaos_tests"],
            "backup_restore": snap["backup_restore_tests"],
            "disaster_recovery": snap["disaster_recovery_tests"],
            "incident_management": snap["incident_management_tests"],
            "resilience_tests": snap["resilience_test_status"],
            "security_integration": snap["security_integration_tests"],
            "backend_tests": "NOT_RUN",
            "frontend_tests": "NOT_RUN",
        }
        print(_write("resilience-evidence.json", report))
        return 0 if report["technical_status"] in {"PASS", "NOT_CERTIFIED"} else 1

    if action == "release":
        print(
            _write(
                "resilience-evidence.json",
                {
                    "schema_version": "1.0.0",
                    "batch": BATCH_NUMBER,
                    "generated_at": datetime.now(UTC).isoformat(),
                    "technical_status": snap["technical_status"],
                    "release_allowed": False,
                    "production_certification": "NOT_CERTIFIED",
                    "evidence": {
                        "slo": snap["slo_checks"]["status"],
                        "error_budget": snap["error_budget_tests"]["status"],
                        "observability": snap["observability_tests"]["status"],
                        "synthetic_monitor": snap["synthetic_monitor_tests"]["status"],
                        "ha": snap["api_ha_tests"]["status"],
                        "security": snap["security_integration_tests"]["status"],
                    },
                },
            )
        )
        return 0 if snap["technical_status"] in {"PASS", "NOT_CERTIFIED"} else 1

    raise ValueError(f"unsupported resilience action: {action}")


def parse_action(parts: list[str]) -> str:
    normalized: list[str] = []
    for part in parts:
        normalized.extend(
            token
            for token in str(part).replace("_", "-").lower().split("-")
            if token
        )

    aliases = {
        ("migrate",): "migrate",
        ("seed",): "seed",
        ("sync",): "sync",
        ("slo",): "slo-check",
        ("slo", "check"): "slo-check",
        ("slo", "checks"): "slo-check",
        ("error", "budget"): "error-budget-test",
        ("error", "budget", "test"): "error-budget-test",
        ("observability",): "observability-test",
        ("observability", "test"): "observability-test",
        ("synthetic", "monitor"): "synthetic-monitor-test",
        ("synthetic", "monitor", "test"): "synthetic-monitor-test",
        ("api", "ha"): "api-ha-test",
        ("api", "ha", "test"): "api-ha-test",
        ("db", "ha"): "database-ha-test",
        ("db", "ha", "test"): "database-ha-test",
        ("database", "ha", "test"): "database-ha-test",
        ("redis", "ha"): "redis-worker-ha-test",
        ("redis", "ha", "test"): "redis-worker-ha-test",
        ("redis", "worker", "ha", "test"): "redis-worker-ha-test",
        ("provider", "fallback"): "provider-resilience-test",
        ("provider", "resilience", "test"): "provider-resilience-test",
        ("degradation", "test"): "degradation-test",
        ("security",): "resilience-security-test",
        ("security", "test"): "resilience-security-test",
        ("admin", "e2e"): "resilience-admin-e2e",
        ("evidence",): "evidence",
        ("evidence", "build"): "evidence",
        ("release",): "release",
        ("chaos", "test"): "chaos-test",
        ("backup", "restore"): "backup-restore-test",
        ("backup", "restore", "test"): "backup-restore-test",
        ("dr", "game", "day"): "dr-game-day-test",
        ("dr", "game", "day", "test"): "dr-game-day-test",
        ("incident",): "incident-management-test",
        ("incident", "management", "test"): "incident-management-test",
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
        raise SystemExit(f"resilience control failed: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
