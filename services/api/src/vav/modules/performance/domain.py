"""Pure performance, capacity and concurrency policies for Batch 29."""

from __future__ import annotations

import math
from collections import defaultdict
from enum import StrEnum
from typing import Any


class WorkloadScale(StrEnum):
    DEVELOPMENT = "development"
    PILOT = "pilot"
    SMALL_PRODUCTION = "small_production"
    MEDIUM_PRODUCTION = "medium_production"
    LARGE_PRODUCTION = "large_production"
    STRESS_BOUNDARY = "stress_boundary"


class PerformanceTestType(StrEnum):
    BASELINE = "baseline"
    LOAD = "load"
    SPIKE = "spike"
    STRESS = "stress"
    SOAK = "soak"
    FAILOVER_LOAD = "failover_load"
    RECOVERY_LOAD = "recovery_load"


class BudgetTargetType(StrEnum):
    API = "api"
    PAGE = "page"
    WORKER_TASK = "worker_task"
    EVENT_CONSUMER = "event_consumer"
    DATABASE_QUERY = "database_query"
    PROVIDER_CALL = "provider_call"
    BUSINESS_JOURNEY = "business_journey"


class SynchronizationMode(StrEnum):
    BARRIER_START = "barrier_start"
    STAGGERED_START = "staggered_start"
    RANDOMIZED_ORDER = "randomized_order"
    PROVIDER_CALLBACK_RACE = "provider_callback_race"
    SCHEDULER_COMMAND_RACE = "scheduler_command_race"


class QueueWorkloadClass(StrEnum):
    SAFETY_CRITICAL = "safety_critical"
    PRIVACY_CRITICAL = "privacy_critical"
    COMMERCE_CRITICAL = "commerce_critical"
    USER_INTERACTIVE = "user_interactive"
    NOTIFICATION = "notification"
    AI = "ai"
    BACKFILL = "backfill"
    ANALYTICS = "analytics"


class RateLimitAlgorithm(StrEnum):
    TOKEN_BUCKET = "token_bucket"
    SLIDING_WINDOW = "sliding_window"
    FIXED_WINDOW = "fixed_window"
    CONCURRENCY_LIMIT = "concurrency_limit"
    COST_WEIGHTED_TOKEN_BUCKET = "cost_weighted_token_bucket"


class PerformanceCertificationStatus(StrEnum):
    NOT_EVALUATED = "not_evaluated"
    FAILED = "failed"
    PASSED_WITH_WARNINGS = "passed_with_warnings"
    PASSED = "passed"


class GateDecision(StrEnum):
    GO = "go"
    NO_GO = "no_go"


CRITICALITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}

PROTECTED_QUEUE_CLASSES = frozenset(
    {
        QueueWorkloadClass.SAFETY_CRITICAL,
        QueueWorkloadClass.PRIVACY_CRITICAL,
        QueueWorkloadClass.COMMERCE_CRITICAL,
    }
)

SHEDDING_ORDER: tuple[str, ...] = (
    QueueWorkloadClass.ANALYTICS,
    QueueWorkloadClass.BACKFILL,
    QueueWorkloadClass.AI,
    QueueWorkloadClass.NOTIFICATION,
    QueueWorkloadClass.USER_INTERACTIVE,
)

IMMEDIATE_INVALIDATION_EVENTS = frozenset(
    {
        "safety.block.created",
        "safety.restriction.created",
        "privacy.erasure.started",
        "contact_exchange.revoked",
        "membership.access_changed",
        "permission.changed",
    }
)

NEVER_CACHEABLE_ASSETS = frozenset(
    {
        "contact_exchange.reveal",
        "safety.block_state",
        "identity.one_time_token",
        "commerce.payment_confirmation",
        "safety.evidence",
    }
)

SUBJECT_BREADTH = {
    "session": 0,
    "ip": 1,
    "user": 1,
    "admin_user": 1,
    "api_key": 2,
    "capability": 2,
    "resource": 2,
    "tenant": 3,
    "provider": 3,
    "global": 4,
}

LATENCY_KEYS: tuple[str, ...] = ("p50_ms", "p90_ms", "p95_ms", "p99_ms", "max_ms")


# --------------------------------------------------------------------------------------
# 1. Production workload model
# --------------------------------------------------------------------------------------


def normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    """Normalize a scenario or role weight map so that the values sum to exactly one."""
    if not weights:
        raise ValueError("weight distribution must not be empty")
    values = {key: float(value) for key, value in weights.items()}
    if any(value < 0 for value in values.values()):
        raise ValueError("weight distribution must not contain negative weights")
    total = sum(values.values())
    if total <= 0:
        raise ValueError("weight distribution must have a positive total")
    return {key: value / total for key, value in sorted(values.items())}


def validate_distribution(weights: dict[str, float], *, tolerance: float = 0.001) -> list[str]:
    """Return findings when a declared distribution is unusable or not normalized."""
    findings: list[str] = []
    if not weights:
        return ["distribution_empty"]
    if any(float(value) < 0 for value in weights.values()):
        findings.append("distribution_negative_weight")
    total = sum(float(value) for value in weights.values())
    if total <= 0:
        findings.append("distribution_total_not_positive")
    elif abs(total - 1.0) > tolerance:
        findings.append("distribution_not_normalized")
    return findings


def derive_target_rps(profile: dict[str, Any]) -> dict[str, float]:
    """Derive average, peak and concurrency targets from business arrival assumptions."""
    daily_active_users = float(profile["daily_active_users"])
    sessions_per_user = float(profile.get("sessions_per_user_per_day", 1.0))
    requests_per_session = float(profile.get("requests_per_session", 1.0))
    active_hours = float(profile.get("active_hours_per_day", 24.0))
    peak_factor = float(profile.get("peak_factor", 1.0))
    session_seconds = float(profile.get("session_duration_seconds", 0.0))
    if min(daily_active_users, sessions_per_user, requests_per_session, session_seconds) < 0:
        raise ValueError("workload profile values must be non-negative")
    if active_hours <= 0:
        raise ValueError("active_hours_per_day must be positive")
    if peak_factor < 1:
        raise ValueError("peak_factor must be at least 1")
    active_seconds = active_hours * 3600.0
    daily_requests = daily_active_users * sessions_per_user * requests_per_session
    average_rps = daily_requests / active_seconds
    session_arrival_rate = daily_active_users * sessions_per_user / active_seconds
    return {
        "daily_requests": round(daily_requests, 4),
        "average_rps": round(average_rps, 4),
        "peak_rps": round(average_rps * peak_factor, 4),
        "session_arrival_rate": round(session_arrival_rate, 6),
        "concurrent_sessions": round(session_arrival_rate * session_seconds * peak_factor, 4),
        "peak_factor": peak_factor,
    }


def scenario_target_rps(peak_rps: float, weights: dict[str, float]) -> dict[str, float]:
    """Split a peak RPS target across weighted traffic scenarios."""
    if peak_rps < 0:
        raise ValueError("peak_rps must be non-negative")
    normalized = normalize_weights(weights)
    return {key: round(peak_rps * value, 4) for key, value in normalized.items()}


def littles_law_concurrency(arrival_rate: float, latency_seconds: float) -> float:
    """Little's law: in-flight work equals arrival rate multiplied by residence time."""
    if arrival_rate < 0 or latency_seconds < 0:
        raise ValueError("arrival_rate and latency_seconds must be non-negative")
    return round(arrival_rate * latency_seconds, 6)


def validate_peak_event(event: dict[str, Any]) -> list[str]:
    """Validate one declared peak event manifest entry."""
    findings: list[str] = []
    for field in (
        "event_code",
        "ramp_seconds",
        "peak_duration_seconds",
        "primary_targets",
        "recovery_budget_seconds",
    ):
        if not event.get(field):
            findings.append(f"peak_event_missing_{field}")
    if float(event.get("peak_multiplier", 0)) < 1:
        findings.append("peak_event_multiplier_below_one")
    if not event.get("expected_degradations"):
        findings.append("peak_event_missing_expected_degradations")
    return findings


def validate_workload_model(model: dict[str, Any]) -> list[str]:
    """Validate a versioned production workload model before it can be approved."""
    findings: list[str] = []
    for field in ("workload_code", "semantic_version", "environment_profile"):
        if not model.get(field):
            findings.append(f"workload_missing_{field}")
    if model.get("scale") not in set(WorkloadScale):
        findings.append("workload_unknown_scale")
    findings.extend(
        f"user_{item}" for item in validate_distribution(model.get("user_distribution") or {})
    )
    findings.extend(
        f"traffic_{item}" for item in validate_distribution(model.get("traffic_distribution") or {})
    )
    concurrency = model.get("concurrency_profile") or {}
    if float(concurrency.get("peak_rps", 0)) <= 0:
        findings.append("workload_missing_peak_rps")
    if float(concurrency.get("concurrent_users", 0)) <= 0:
        findings.append("workload_missing_concurrent_users")
    if not model.get("background_job_profile"):
        findings.append("workload_missing_background_job_profile")
    if not model.get("provider_profile"):
        findings.append("workload_missing_provider_profile")
    if not model.get("growth_assumptions"):
        findings.append("workload_missing_growth_assumptions")
    for event in model.get("peak_event_manifest") or []:
        findings.extend(validate_peak_event(event))
    for key, value in (model.get("value_provenance") or {}).items():
        if value not in {"measured", "assumed", "inferred"}:
            findings.append(f"workload_unlabelled_provenance_{key}")
    declared = set(model.get("value_provenance") or {})
    if "concurrency_profile" not in declared:
        findings.append("workload_missing_provenance_concurrency_profile")
    return sorted(set(findings))


# --------------------------------------------------------------------------------------
# 2. Endpoint and journey performance budgets
# --------------------------------------------------------------------------------------


def merge_budget(parent: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    """Inherit a module-level budget into an endpoint-level budget; child values win."""
    merged: dict[str, Any] = {}
    for section in set(parent) | set(child):
        parent_section = parent.get(section)
        child_section = child.get(section)
        if isinstance(parent_section, dict) and isinstance(child_section, dict):
            merged[section] = {**parent_section, **child_section}
        elif child_section is not None:
            merged[section] = child_section
        else:
            merged[section] = parent_section
    return merged


def validate_budget(budget: dict[str, Any]) -> list[str]:
    """Reject budgets missing long-tail latency, error or throughput commitments."""
    findings: list[str] = []
    latency = budget.get("latency_budget") or {}
    errors = budget.get("error_budget") or {}
    throughput = budget.get("throughput_budget") or {}
    for key in ("p50_ms", "p95_ms", "p99_ms"):
        if key not in latency:
            findings.append(f"budget_missing_{key}")
    for key in ("error_rate", "timeout_rate"):
        if key not in errors:
            findings.append(f"budget_missing_{key}")
    if "minimum_rps" not in throughput:
        findings.append("budget_missing_minimum_rps")
    present = [key for key in LATENCY_KEYS if key in latency]
    for first, second in zip(present, present[1:], strict=False):
        if float(latency[first]) > float(latency[second]):
            findings.append("budget_percentiles_not_monotonic")
            break
    for value in latency.values():
        if float(value) <= 0:
            findings.append("budget_non_positive_latency")
            break
    if not budget.get("workload_code"):
        findings.append("budget_not_bound_to_workload")
    if budget.get("criticality") not in CRITICALITY_ORDER:
        findings.append("budget_unknown_criticality")
    return sorted(set(findings))


def evaluate_budget(
    budget: dict[str, Any], observed: dict[str, Any], *, warning_ratio: float = 0.85
) -> dict[str, Any]:
    """Compare an observed measurement set with a resolved budget."""
    breaches: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    checked = 0
    for section, keys in (
        ("latency_budget", LATENCY_KEYS),
        ("error_budget", ("error_rate", "timeout_rate")),
        ("resource_budget", ("cpu_ratio", "memory_ratio", "db_pool_ratio")),
    ):
        limits = budget.get(section) or {}
        for key in keys:
            if key not in limits or key not in observed:
                continue
            checked += 1
            limit = float(limits[key])
            value = float(observed[key])
            record = {
                "metric": key,
                "budget": limit,
                "observed": value,
                "ratio": round(value / limit, 6) if limit else None,
            }
            if value > limit:
                breaches.append(record)
            elif limit and value >= limit * warning_ratio:
                warnings.append(record)
    throughput = budget.get("throughput_budget") or {}
    if "minimum_rps" in throughput and "achieved_rps" in observed:
        checked += 1
        minimum = float(throughput["minimum_rps"])
        achieved = float(observed["achieved_rps"])
        if achieved < minimum:
            breaches.append(
                {
                    "metric": "achieved_rps",
                    "budget": minimum,
                    "observed": achieved,
                    "ratio": round(achieved / minimum, 6) if minimum else None,
                }
            )
    status = "failed" if breaches else ("passed_with_warnings" if warnings else "passed")
    if checked == 0:
        status = "not_evaluated"
    return {
        "status": status,
        "checked_metrics": checked,
        "breaches": breaches,
        "warnings": warnings,
    }


def compare_to_baseline(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    tolerance_ratio: float = 0.10,
    noise_band_ms: float = 15.0,
    minimum_samples: int = 30,
) -> dict[str, Any]:
    """Detect statistically meaningful latency regressions against an approved baseline."""
    metrics: list[dict[str, Any]] = []
    if int(candidate.get("sample_count", 0)) < minimum_samples or (
        int(baseline.get("sample_count", 0)) < minimum_samples
    ):
        return {
            "status": "insufficient_samples",
            "regressed": False,
            "metrics": [],
            "minimum_samples": minimum_samples,
        }
    for key in LATENCY_KEYS:
        if key not in baseline or key not in candidate:
            continue
        before = float(baseline[key])
        after = float(candidate[key])
        delta = after - before
        relative = delta / before if before else math.inf
        outside_noise = abs(delta) > noise_band_ms
        outside_tolerance = abs(relative) > tolerance_ratio
        if delta > 0 and outside_noise and outside_tolerance:
            verdict = "regressed"
        elif delta < 0 and outside_noise and outside_tolerance:
            verdict = "improved"
        else:
            verdict = "stable"
        metrics.append(
            {
                "metric": key,
                "baseline": before,
                "candidate": after,
                "delta_ms": round(delta, 4),
                "relative_change": round(relative, 6),
                "verdict": verdict,
            }
        )
    regressed = [item for item in metrics if item["verdict"] == "regressed"]
    return {
        "status": "regressed" if regressed else "stable",
        "regressed": bool(regressed),
        "regressed_metrics": [item["metric"] for item in regressed],
        "metrics": metrics,
        "tolerance_ratio": tolerance_ratio,
        "noise_band_ms": noise_band_ms,
    }


def budget_pass_ratio(results: list[dict[str, Any]], *, criticality: str = "critical") -> float:
    """Pass ratio restricted to a criticality tier; an empty tier is fail-closed at zero."""
    scoped = [item for item in results if item.get("criticality") == criticality]
    if not scoped:
        return 0.0
    passed = sum(1 for item in scoped if item.get("status") in {"passed", "passed_with_warnings"})
    return round(passed / len(scoped), 5)


# --------------------------------------------------------------------------------------
# 3. Concurrency hotspots and race scenarios
# --------------------------------------------------------------------------------------


def detect_write_hotspots(
    operations: list[dict[str, Any]], *, contention_threshold: int = 2
) -> list[dict[str, Any]]:
    """Identify resources where concurrent actors write the same row or key."""
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for operation in operations:
        resource = str(operation["resource"])
        key = str(operation.get("key", "*"))
        bucket = grouped.setdefault(
            (resource, key),
            {"resource": resource, "key": key, "writers": 0, "readers": 0, "scenarios": set()},
        )
        actors = int(operation.get("actors", 1))
        if str(operation.get("mode", "write")) == "write":
            bucket["writers"] += actors
        else:
            bucket["readers"] += actors
        if operation.get("scenario_code"):
            bucket["scenarios"].add(str(operation["scenario_code"]))
    hotspots: list[dict[str, Any]] = []
    for bucket in grouped.values():
        writers = int(bucket["writers"])
        if writers < contention_threshold:
            continue
        if writers >= 50:
            severity = "critical"
        elif writers >= 10:
            severity = "high"
        else:
            severity = "medium"
        hotspots.append(
            {
                "resource": bucket["resource"],
                "key": bucket["key"],
                "concurrent_writers": writers,
                "concurrent_readers": int(bucket["readers"]),
                "mixed_read_write": bool(bucket["readers"]) and bool(writers),
                "severity": severity,
                "scenarios": sorted(bucket["scenarios"]),
            }
        )
    return sorted(hotspots, key=lambda item: (-item["concurrent_writers"], item["resource"]))


def detect_lock_cycles(
    lock_orders: dict[str, list[str]], *, max_depth: int = 24
) -> list[list[str]]:
    """Detect deadlock-prone lock-order cycles across declared transaction lock sequences."""
    edges: dict[str, set[str]] = defaultdict(set)
    for order in lock_orders.values():
        for first, second in zip(order, order[1:], strict=False):
            if first != second:
                edges[str(first)].add(str(second))
    cycles: set[tuple[str, ...]] = set()

    def visit(node: str, path: list[str]) -> None:
        if len(path) > max_depth:
            return
        for following in sorted(edges.get(node, set())):
            if following in path:
                cycle = path[path.index(following) :]
                rotation = cycle.index(min(cycle))
                cycles.add(tuple(cycle[rotation:] + cycle[:rotation]))
                continue
            visit(following, [*path, following])

    for node in sorted(edges):
        visit(node, [node])
    return [list(item) for item in sorted(cycles)]


def validate_idempotency_coverage(scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every mutating race scenario needs an idempotency key and an invariant assertion."""
    findings: list[dict[str, Any]] = []
    for scenario in scenarios:
        code = str(scenario.get("scenario_code", "unknown"))
        reasons: list[str] = []
        mutating = bool(scenario.get("mutating", True))
        if mutating and not scenario.get("idempotency_key_expression"):
            reasons.append("missing_idempotency_key")
        if not scenario.get("expected_invariants"):
            reasons.append("missing_expected_invariants")
        if not scenario.get("expected_result_distribution"):
            reasons.append("missing_expected_result_distribution")
        if scenario.get("synchronization_mode") not in set(SynchronizationMode):
            reasons.append("unknown_synchronization_mode")
        if int(scenario.get("concurrent_actor_count", 0)) < 2:
            reasons.append("insufficient_concurrent_actors")
        if scenario.get("synchronization_mode") == SynchronizationMode.PROVIDER_CALLBACK_RACE and (
            not scenario.get("duplicate_callback_expected")
        ):
            reasons.append("callback_race_missing_duplicate_expectation")
        if reasons:
            findings.append({"scenario_code": code, "reasons": sorted(reasons)})
    return sorted(findings, key=lambda item: item["scenario_code"])


def evaluate_race_result(scenario: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
    """Compare an executed race schedule with the declared invariants and distribution."""
    violations: list[str] = []
    expected = scenario.get("expected_result_distribution") or {}
    for outcome, count in expected.items():
        if int(observed.get("result_distribution", {}).get(outcome, -1)) != int(count):
            violations.append(f"result_distribution_mismatch:{outcome}")
    for invariant, expectation in (scenario.get("expected_invariants") or {}).items():
        if observed.get("invariants", {}).get(invariant) != expectation:
            violations.append(f"invariant_failed:{invariant}")
    if int(observed.get("duplicate_side_effects", 0)) > 0:
        violations.append("duplicate_side_effects")
    total_actors = int(scenario.get("concurrent_actor_count", 0))
    resolved = sum(int(value) for value in (observed.get("result_distribution") or {}).values())
    if total_actors and resolved != total_actors:
        violations.append("unresolved_actors")
    return {
        "scenario_code": scenario.get("scenario_code"),
        "passed": not violations,
        "violations": sorted(set(violations)),
        "criticality": scenario.get("criticality", "critical"),
    }


# --------------------------------------------------------------------------------------
# 4. Baseline, load, spike, stress and soak evaluation
# --------------------------------------------------------------------------------------


def linear_slope(samples: list[tuple[float, float]]) -> float:
    """Least-squares slope of a time series expressed as (x, y) pairs."""
    points = [(float(x), float(y)) for x, y in samples]
    count = len(points)
    if count < 2:
        return 0.0
    mean_x = sum(x for x, _ in points) / count
    mean_y = sum(y for _, y in points) / count
    denominator = sum((x - mean_x) ** 2 for x, _ in points)
    if denominator == 0:
        return 0.0
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in points)
    return numerator / denominator


def evaluate_soak(
    series: dict[str, list[tuple[float, float]]],
    *,
    leak_thresholds: dict[str, float] | None = None,
    minimum_duration_hours: float = 8.0,
    relative_growth_limit: float = 0.10,
) -> dict[str, Any]:
    """Detect resource leakage from soak-test time series (hours on the x axis)."""
    thresholds = leak_thresholds or {}
    metrics: list[dict[str, Any]] = []
    duration_hours = 0.0
    for name, samples in sorted(series.items()):
        if not samples:
            continue
        ordered = sorted(((float(x), float(y)) for x, y in samples), key=lambda item: item[0])
        duration_hours = max(duration_hours, ordered[-1][0] - ordered[0][0])
        slope = linear_slope(ordered)
        first = ordered[0][1]
        last = ordered[-1][1]
        relative_growth = (last - first) / first if first else math.inf
        threshold = float(thresholds.get(name, 0.0))
        is_leaking = slope > threshold and relative_growth > relative_growth_limit
        metrics.append(
            {
                "metric": name,
                "slope_per_hour": round(slope, 6),
                "threshold_per_hour": threshold,
                "first_value": first,
                "last_value": last,
                "relative_growth": round(relative_growth, 6),
                "leaking": is_leaking,
            }
        )
    leaking_metrics = [item["metric"] for item in metrics if item["leaking"]]
    duration_ok = duration_hours >= minimum_duration_hours
    status = (
        "failed" if not metrics or not duration_ok else "failed" if leaking_metrics else "passed"
    )
    return {
        "status": status,
        "duration_hours": round(duration_hours, 4),
        "duration_sufficient": duration_ok,
        "leaking_metrics": sorted(leaking_metrics),
        "metrics": metrics,
    }


def find_knee_point(
    points: list[dict[str, Any]],
    *,
    max_error_rate: float = 0.01,
    latency_budget_ms: float | None = None,
    efficiency_floor: float = 0.5,
) -> dict[str, Any]:
    """Locate the stress knee point, maximum stable throughput and saturation load."""
    if not points:
        return {
            "status": "not_evaluated",
            "knee_rps": None,
            "max_stable_rps": 0.0,
            "saturation_rps": None,
            "failure_rps": None,
            "steps": [],
        }
    ordered = sorted(points, key=lambda item: float(item["offered_rps"]))
    steps: list[dict[str, Any]] = []
    knee: float | None = None
    saturation: float | None = None
    failure: float | None = None
    max_stable = 0.0
    previous_achieved = 0.0
    first_gain: float | None = None
    for index, point in enumerate(ordered):
        offered = float(point["offered_rps"])
        achieved = float(point.get("achieved_rps", offered))
        error_rate = float(point.get("error_rate", 0.0))
        p95 = float(point.get("p95_ms", 0.0))
        healthy = error_rate <= max_error_rate and (
            latency_budget_ms is None or p95 <= latency_budget_ms
        )
        gain = achieved - previous_achieved
        if index == 1:
            first_gain = gain
        if healthy:
            max_stable = max(max_stable, achieved)
        if (
            knee is None
            and first_gain is not None
            and first_gain > 0
            and index >= 2
            and gain < first_gain * efficiency_floor
        ):
            knee = offered
        if knee is None and index >= 1 and not healthy:
            knee = offered
        if saturation is None and index >= 1 and achieved < previous_achieved:
            saturation = offered
        if failure is None and (error_rate > 0.5 or achieved <= 0):
            failure = offered
        steps.append(
            {
                "offered_rps": offered,
                "achieved_rps": achieved,
                "error_rate": error_rate,
                "p95_ms": p95,
                "healthy": healthy,
                "throughput_gain": round(gain, 4),
            }
        )
        previous_achieved = achieved
    return {
        "status": "evaluated",
        "knee_rps": knee,
        "max_stable_rps": round(max_stable, 4),
        "saturation_rps": saturation,
        "failure_rps": failure,
        "steps": steps,
    }


def evaluate_stress(
    points: list[dict[str, Any]],
    *,
    data_corruption_detected: bool = False,
    authorization_bypass_detected: bool = False,
    recovered_after_stress: bool = True,
    max_error_rate: float = 0.01,
    latency_budget_ms: float | None = None,
) -> dict[str, Any]:
    """Stress tolerates failure but never corruption, bypass or an unrecoverable system."""
    knee = find_knee_point(
        points, max_error_rate=max_error_rate, latency_budget_ms=latency_budget_ms
    )
    blocking: list[str] = []
    if data_corruption_detected:
        blocking.append("data_corruption")
    if authorization_bypass_detected:
        blocking.append("authorization_bypass")
    if not recovered_after_stress:
        blocking.append("not_recoverable")
    if knee["status"] == "not_evaluated" or knee["max_stable_rps"] <= 0:
        blocking.append("no_stable_throughput_measured")
    return {
        "blocking_reasons": sorted(blocking),
        **knee,
        "status": "failed" if blocking else "passed",
    }


def evaluate_spike(
    samples: list[dict[str, Any]],
    *,
    spike_end_seconds: float,
    baseline_p95_ms: float,
    recovery_budget_seconds: float,
    recovery_tolerance_ratio: float = 1.2,
    max_error_rate: float = 0.05,
) -> dict[str, Any]:
    """Measure spike recovery time and the worst error rate observed during the spike."""
    ordered = sorted(samples, key=lambda item: float(item["t_seconds"]))
    during = [item for item in ordered if float(item["t_seconds"]) <= spike_end_seconds]
    after = [item for item in ordered if float(item["t_seconds"]) > spike_end_seconds]
    peak_error_rate = max((float(item.get("error_rate", 0.0)) for item in during), default=0.0)
    peak_p95 = max((float(item.get("p95_ms", 0.0)) for item in during), default=0.0)
    recovery_limit = baseline_p95_ms * recovery_tolerance_ratio
    recovery_seconds: float | None = None
    for index, item in enumerate(after):
        healthy = float(item.get("p95_ms", 0.0)) <= recovery_limit and (
            float(item.get("error_rate", 0.0)) <= max_error_rate
        )
        if not healthy:
            continue
        if all(
            float(later.get("p95_ms", 0.0)) <= recovery_limit
            and float(later.get("error_rate", 0.0)) <= max_error_rate
            for later in after[index:]
        ):
            recovery_seconds = float(item["t_seconds"]) - spike_end_seconds
            break
    reasons: list[str] = []
    if not after:
        reasons.append("missing_post_spike_samples")
    if recovery_seconds is None:
        reasons.append("did_not_recover")
    elif recovery_seconds > recovery_budget_seconds:
        reasons.append("recovery_budget_exceeded")
    if peak_error_rate > max_error_rate:
        reasons.append("spike_error_rate_exceeded")
    return {
        "status": "failed" if reasons else "passed",
        "recovery_seconds": recovery_seconds,
        "recovery_budget_seconds": recovery_budget_seconds,
        "peak_error_rate": round(peak_error_rate, 6),
        "peak_p95_ms": round(peak_p95, 4),
        "recovery_limit_ms": round(recovery_limit, 4),
        "blocking_reasons": sorted(reasons),
    }
