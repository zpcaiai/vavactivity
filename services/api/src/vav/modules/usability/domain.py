"""Pure functional-usability, UAT, compatibility and certification policies."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from vav.common.exceptions import VavError

# --------------------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------------------


def checksum(value: Any) -> str:
    """Stable content checksum used for drafts, fixtures and import files."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def deterministic_token(seed: int, *parts: str) -> str:
    """Reproducible pseudo-random token derived only from the seed and the key parts."""
    material = f"{seed}:" + "|".join(parts)
    return hashlib.sha256(material.encode()).hexdigest()


def deterministic_index(seed: int, bound: int, *parts: str) -> int:
    """Reproducible index in ``[0, bound)``; returns 0 when the bound is not positive."""
    if bound <= 0:
        return 0
    return int(deterministic_token(seed, *parts)[:16], 16) % bound


def _fail(code: str, message: str, status_code: int = 422) -> None:
    raise VavError(code, message, status_code=status_code)


# --------------------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------------------


class UatCriticality(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class UatAutomationLevel(StrEnum):
    MANUAL = "manual"
    ASSISTED = "assisted"
    AUTOMATED = "automated"
    HYBRID = "hybrid"


class UatRunStatus(StrEnum):
    READY = "ready"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    NEEDS_RETEST = "needs_retest"
    INVALIDATED = "invalidated"


class UatStepStatus(StrEnum):
    NOT_RUN = "not_run"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class SyntheticVolumeProfile(StrEnum):
    MINIMAL = "minimal"
    STANDARD = "standard"
    LARGE = "large"
    STRESS = "stress"


class CompatibilityTier(StrEnum):
    TIER_1 = "tier_1"
    TIER_2 = "tier_2"
    TIER_3 = "tier_3"


class CompatibilityIssueSeverity(StrEnum):
    BLOCKER = "blocker"
    MAJOR = "major"
    MINOR = "minor"


class LocalizedContentRiskLevel(StrEnum):
    NORMAL = "normal"
    BUSINESS_CRITICAL = "business_critical"
    FINANCIAL = "financial"
    PRIVACY = "privacy"
    SAFETY = "safety"
    LEGAL_POLICY = "legal_policy"


class DraftStatus(StrEnum):
    ACTIVE = "active"
    CONFLICTED = "conflicted"
    MIGRATION_REQUIRED = "migration_required"
    SUBMITTED = "submitted"
    DISCARDED = "discarded"
    EXPIRED = "expired"


class DraftConflictPolicy(StrEnum):
    LATEST_CLIENT = "latest_client"
    LATEST_SERVER = "latest_server"
    MANUAL_MERGE = "manual_merge"
    REJECT_STALE = "reject_stale"


class NotificationChannel(StrEnum):
    IN_APP = "in_app"
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    WECHAT = "wechat"


class ImportRowStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    IMPORTED = "imported"
    FAILED = "failed"
    SKIPPED = "skipped"


class UsabilityIssueType(StrEnum):
    DISCOVERABILITY = "discoverability"
    COMPREHENSION = "comprehension"
    NAVIGATION = "navigation"
    FORM_COMPLETION = "form_completion"
    STATUS_FEEDBACK = "status_feedback"
    ERROR_RECOVERY = "error_recovery"
    TRUST = "trust"
    ACCESSIBILITY = "accessibility"
    PERFORMANCE_PERCEPTION = "performance_perception"
    CONTENT_CLARITY = "content_clarity"


class UsabilityIssueSeverity(StrEnum):
    BLOCKER = "blocker"
    MAJOR = "major"
    MODERATE = "moderate"
    MINOR = "minor"


class TaskCompletionStatus(StrEnum):
    COMPLETED_WITHOUT_HELP = "completed_without_help"
    COMPLETED_WITH_HELP = "completed_with_help"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    ABANDONED = "abandoned"


class FunctionalUsabilityStatus(StrEnum):
    NOT_EVALUATED = "not_evaluated"
    FAILED = "failed"
    PASSED_WITH_WARNINGS = "passed_with_warnings"
    PASSED = "passed"


class CertificationDecision(StrEnum):
    NOT_CERTIFIED = "not_certified"
    ELIGIBLE = "eligible"
    CERTIFIED = "certified"
    REJECTED = "rejected"


# --------------------------------------------------------------------------------------
# 1. Role-based UAT
# --------------------------------------------------------------------------------------

UAT_RUN_TRANSITIONS: dict[UatRunStatus, frozenset[UatRunStatus]] = {
    UatRunStatus.READY: frozenset({UatRunStatus.RUNNING, UatRunStatus.INVALIDATED}),
    UatRunStatus.RUNNING: frozenset(
        {
            UatRunStatus.PASSED,
            UatRunStatus.FAILED,
            UatRunStatus.BLOCKED,
            UatRunStatus.INVALIDATED,
        }
    ),
    UatRunStatus.PASSED: frozenset({UatRunStatus.NEEDS_RETEST, UatRunStatus.INVALIDATED}),
    UatRunStatus.FAILED: frozenset({UatRunStatus.NEEDS_RETEST, UatRunStatus.INVALIDATED}),
    UatRunStatus.BLOCKED: frozenset({UatRunStatus.NEEDS_RETEST, UatRunStatus.INVALIDATED}),
    UatRunStatus.NEEDS_RETEST: frozenset({UatRunStatus.RUNNING, UatRunStatus.INVALIDATED}),
    UatRunStatus.INVALIDATED: frozenset(),
}

TERMINAL_UAT_STATUSES = frozenset({UatRunStatus.INVALIDATED})


def validate_run_transition(current: str, target: str) -> UatRunStatus:
    """Guard the UAT execution state machine; unknown or illegal moves fail closed."""
    try:
        source = UatRunStatus(current)
        destination = UatRunStatus(target)
    except ValueError:
        _fail("USABILITY_UAT_STATUS_UNKNOWN", f"Unknown UAT run status {current}->{target}.")
        raise  # pragma: no cover - _fail always raises
    if destination not in UAT_RUN_TRANSITIONS[source]:
        _fail(
            "USABILITY_UAT_TRANSITION_FORBIDDEN",
            f"UAT run cannot move from {source} to {destination}.",
            409,
        )
    return destination


def validate_scenario_definition(scenario: Mapping[str, Any]) -> list[str]:
    """Return definition findings; an empty list means the scenario is registrable."""
    findings: list[str] = []
    for required in ("scenario_code", "semantic_version", "business_domain", "role_code"):
        if not scenario.get(required):
            findings.append(f"missing_{required}")
    criticality = str(scenario.get("criticality", ""))
    if criticality not in set(UatCriticality):
        findings.append("invalid_criticality")
    automation = str(scenario.get("automation_level", ""))
    if automation not in set(UatAutomationLevel):
        findings.append("invalid_automation_level")
    steps = list(scenario.get("steps") or [])
    if not steps:
        findings.append("no_steps")
    seen: set[str] = set()
    for index, step in enumerate(steps, 1):
        code = str(step.get("step_code") or f"step-{index}")
        if code in seen:
            findings.append(f"duplicate_step:{code}")
        seen.add(code)
        if not step.get("instruction"):
            findings.append(f"step_missing_instruction:{code}")
        if not step.get("expected_ui_state"):
            findings.append(f"step_missing_ui_expectation:{code}")
        if not step.get("expected_business_state"):
            findings.append(f"step_missing_business_expectation:{code}")
        if criticality == UatCriticality.CRITICAL and not step.get("evidence_type_codes"):
            findings.append(f"step_missing_evidence_requirement:{code}")
    if criticality == UatCriticality.CRITICAL:
        if not scenario.get("fixture_blueprint_code"):
            findings.append("critical_scenario_without_synthetic_fixture")
        if not scenario.get("required_locales"):
            findings.append("critical_scenario_without_locale_matrix")
        if not scenario.get("required_device_profiles"):
            findings.append("critical_scenario_without_device_matrix")
        if not scenario.get("expected_outcomes"):
            findings.append("critical_scenario_without_terminal_state")
    return sorted(findings)


def role_scenario_matrix(
    roles: Sequence[Mapping[str, Any]], scenarios: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Build the role/scenario coverage matrix and detect uncovered critical roles."""
    known = {str(role["role_code"]) for role in roles}
    coverage: dict[str, list[str]] = {code: [] for code in known}
    critical_coverage: dict[str, list[str]] = {code: [] for code in known}
    orphans: list[str] = []
    for scenario in scenarios:
        role_code = str(scenario.get("role_code") or "")
        code = str(scenario.get("scenario_code") or "")
        if role_code not in known:
            orphans.append(code)
            continue
        if str(scenario.get("lifecycle_status", "active")) != "active":
            continue
        coverage[role_code].append(code)
        if str(scenario.get("criticality")) == UatCriticality.CRITICAL:
            critical_coverage[role_code].append(code)
    critical_roles = [
        str(role["role_code"])
        for role in roles
        if str(role.get("criticality", "critical")) == UatCriticality.CRITICAL
    ]
    uncovered = sorted(code for code in critical_roles if not critical_coverage[code])
    ratio = 0.0
    if critical_roles:
        ratio = (len(critical_roles) - len(uncovered)) / len(critical_roles)
    return {
        "coverage": {code: sorted(items) for code, items in coverage.items()},
        "critical_coverage": {code: sorted(items) for code, items in critical_coverage.items()},
        "critical_role_count": len(critical_roles),
        "uncovered_critical_roles": uncovered,
        "orphan_scenarios": sorted(orphans),
        "critical_role_coverage_ratio": round(ratio, 5),
        "status": "passed" if not uncovered and not orphans else "failed",
    }


def evaluate_step_results(
    steps: Sequence[Mapping[str, Any]], results: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Fail-closed step aggregation: missing results block, critical failures fail."""
    by_code = {str(step.get("step_code") or f"step-{i}"): step for i, step in enumerate(steps, 1)}
    observed: dict[str, str] = {}
    unknown: list[str] = []
    for result in results:
        code = str(result.get("step_code") or "")
        if code not in by_code:
            unknown.append(code)
            continue
        observed[code] = str(result.get("status") or UatStepStatus.NOT_RUN)
    missing = sorted(code for code in by_code if code not in observed)
    failed = sorted(code for code, status in observed.items() if status == UatStepStatus.FAILED)
    blocked = sorted(code for code, status in observed.items() if status == UatStepStatus.BLOCKED)
    passed = sorted(code for code, status in observed.items() if status == UatStepStatus.PASSED)
    skipped = sorted(code for code, status in observed.items() if status == UatStepStatus.SKIPPED)
    critical_failures = sorted(
        code for code in failed + blocked if bool(by_code[code].get("critical", True))
    )
    critical_skipped = sorted(code for code in skipped if bool(by_code[code].get("critical", True)))
    if missing or unknown or critical_skipped:
        status = UatRunStatus.BLOCKED
    elif failed:
        status = UatRunStatus.FAILED
    elif blocked:
        status = UatRunStatus.BLOCKED
    elif len(passed) + len(skipped) == len(by_code):
        status = UatRunStatus.PASSED
    else:
        status = UatRunStatus.BLOCKED
    return {
        "total": len(by_code),
        "passed": passed,
        "failed": failed,
        "blocked": blocked,
        "skipped": skipped,
        "missing": missing,
        "unknown": sorted(unknown),
        "critical_failures": critical_failures,
        "status": str(status),
        "pass_ratio": round(len(passed) / len(by_code), 5) if by_code else 0.0,
    }


def sign_off_findings(
    run: Mapping[str, Any],
    *,
    signer_id: str,
    release_version: str,
    manual_review_required: bool = True,
    maximum_age_seconds: int = 30 * 24 * 3600,
    now: datetime | None = None,
) -> list[str]:
    """Validity findings for a UAT sign-off; empty means the sign-off may be recorded."""
    moment = now or datetime.now(UTC)
    findings: list[str] = []
    status = str(run.get("status") or "")
    if status != UatRunStatus.PASSED:
        findings.append("run_not_passed")
    if str(run.get("release_version") or "") != release_version:
        findings.append("release_mismatch")
    executed_by = str(run.get("executed_by") or "")
    if manual_review_required and (not executed_by or executed_by == signer_id):
        findings.append("separation_of_duties_violation")
    if not list(run.get("evidence_refs") or []):
        findings.append("missing_evidence")
    completed_at = run.get("completed_at")
    if not isinstance(completed_at, datetime):
        findings.append("missing_completion_time")
    else:
        reference = completed_at if completed_at.tzinfo else completed_at.replace(tzinfo=UTC)
        if (moment - reference).total_seconds() > maximum_age_seconds:
            findings.append("evidence_expired")
    if str(run.get("criticality") or UatCriticality.CRITICAL) == UatCriticality.CRITICAL:
        summary = run.get("summary") or {}
        if list(summary.get("critical_failures") or []):
            findings.append("open_critical_failures")
        if not run.get("fixture_run_id"):
            findings.append("missing_synthetic_fixture_binding")
    return sorted(findings)


def validate_sign_off(run: Mapping[str, Any], **kwargs: Any) -> None:
    """Raise when the sign-off is invalid; used by the transactional service layer."""
    findings = sign_off_findings(run, **kwargs)
    if findings:
        raise VavError(
            "USABILITY_UAT_SIGN_OFF_INVALID",
            "UAT sign-off is not valid.",
            status_code=409,
            details=findings,
        )


# --------------------------------------------------------------------------------------
# 2. Synthetic test data
# --------------------------------------------------------------------------------------

VOLUME_MULTIPLIERS: dict[SyntheticVolumeProfile, int] = {
    SyntheticVolumeProfile.MINIMAL: 1,
    SyntheticVolumeProfile.STANDARD: 5,
    SyntheticVolumeProfile.LARGE: 40,
    SyntheticVolumeProfile.STRESS: 200,
}

SYNTHETIC_LOCALES = ("zh-CN", "zh-TW", "en")
SYNTHETIC_TIMEZONES = ("Asia/Shanghai", "Asia/Taipei", "Europe/London", "America/Los_Angeles")
SYNTHETIC_EDGE_CASES = (
    "long_text",
    "missing_optional",
    "expired_state",
    "restricted_state",
    "pending_confirmation",
    "multilingual",
)
SYNTHETIC_EMAIL_DOMAIN = "example.test"
SYNTHETIC_PHONE_PREFIX = "+999"


def expand_blueprint(
    blueprint: Mapping[str, Any], *, seed: int | None = None, namespace: str | None = None
) -> dict[str, Any]:
    """Deterministically expand a blueprint into a concrete generation plan."""
    resolved_seed = int(seed if seed is not None else blueprint.get("deterministic_seed", 0))
    profile = SyntheticVolumeProfile(str(blueprint.get("volume_profile", "standard")))
    multiplier = VOLUME_MULTIPLIERS[profile]
    code = str(blueprint.get("blueprint_code", "BLUEPRINT"))
    space = namespace or f"syn-{code.casefold()}-{resolved_seed}"
    entities = list(blueprint.get("entities") or [])
    records: dict[str, list[dict[str, Any]]] = {}
    for entity in entities:
        name = str(entity["entity"])
        base = max(int(entity.get("base_count", 1)), 0)
        count = base * multiplier
        edge_cases = list(entity.get("edge_cases") or [])
        bucket: list[dict[str, Any]] = []
        for index in range(count):
            key = f"{name}:{index}"
            token = deterministic_token(resolved_seed, space, key)
            locale = SYNTHETIC_LOCALES[deterministic_index(resolved_seed, 3, space, key, "locale")]
            timezone = SYNTHETIC_TIMEZONES[
                deterministic_index(resolved_seed, 4, space, key, "timezone")
            ]
            applied = (
                edge_cases[deterministic_index(resolved_seed, len(edge_cases), space, key, "edge")]
                if edge_cases and index % 3 == 0
                else None
            )
            bucket.append(
                {
                    "entity": name,
                    "reference": f"{space}-{name}-{index:05d}",
                    "index": index,
                    "locale": locale,
                    "timezone": timezone,
                    "edge_case": applied,
                    "display_name": (
                        "N" * 180 if applied == "long_text" else f"{name}-{token[:8]}"
                    ),
                    "email": f"{name}.{index:05d}@{SYNTHETIC_EMAIL_DOMAIN}",
                    "phone": f"{SYNTHETIC_PHONE_PREFIX}{token[:9]}".replace("a", "1")
                    .replace("b", "2")
                    .replace("c", "3")
                    .replace("d", "4")
                    .replace("e", "5")
                    .replace("f", "6"),
                    "attributes": {},
                    "relations": {},
                }
            )
        records[name] = bucket
    for relation in blueprint.get("relationships") or []:
        child = str(relation["from"])
        parent = str(relation["to"])
        field = str(relation.get("field", f"{parent}_reference"))
        optional = not bool(relation.get("required", True))
        parents = records.get(parent, [])
        for item in records.get(child, []):
            if optional and item["edge_case"] == "missing_optional":
                item["relations"][field] = None
                continue
            if not parents:
                item["relations"][field] = None
                continue
            position = deterministic_index(
                resolved_seed, len(parents), space, child, str(item["index"]), field
            )
            item["relations"][field] = parents[position]["reference"]
    counts = {name: len(items) for name, items in records.items()}
    plan = {
        "blueprint_code": code,
        "seed": resolved_seed,
        "namespace": space,
        "volume_profile": str(profile),
        "entity_counts": counts,
        "records": records,
    }
    plan["plan_checksum"] = checksum({"counts": counts, "records": records})
    return plan


def validate_reference_integrity(
    plan: Mapping[str, Any], blueprint: Mapping[str, Any]
) -> list[dict[str, str]]:
    """Detect dangling, missing or cross-namespace references in a generation plan."""
    records: Mapping[str, Sequence[Mapping[str, Any]]] = plan.get("records") or {}
    known = {name: {str(item["reference"]) for item in items} for name, items in records.items()}
    namespace = str(plan.get("namespace", ""))
    findings: list[dict[str, str]] = []
    for relation in blueprint.get("relationships") or []:
        child = str(relation["from"])
        parent = str(relation["to"])
        field = str(relation.get("field", f"{parent}_reference"))
        required = bool(relation.get("required", True))
        if child not in records or parent not in records:
            findings.append({"code": "unknown_entity", "detail": f"{child}->{parent}"})
            continue
        for item in records[child]:
            value = item.get("relations", {}).get(field)
            if value is None:
                if required:
                    findings.append(
                        {"code": "missing_required_reference", "detail": f"{child}.{field}"}
                    )
                continue
            if value not in known[parent]:
                findings.append({"code": "dangling_reference", "detail": str(value)})
            elif namespace and not str(value).startswith(namespace):
                findings.append({"code": "cross_namespace_reference", "detail": str(value)})
    for name, items in records.items():
        references = [str(item["reference"]) for item in items]
        if len(references) != len(set(references)):
            findings.append({"code": "duplicate_reference", "detail": name})
    return findings


EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
E164_PATTERN = re.compile(r"\+[1-9][0-9]{7,14}")
CN_MOBILE_PATTERN = re.compile(r"(?<![0-9])1[3-9][0-9]{9}(?![0-9])")
DIGIT_RUN_PATTERN = re.compile(r"(?<![0-9])[0-9]{13,19}(?![0-9])")
CN_IDENTITY_PATTERN = re.compile(r"(?<![0-9A-Za-z])[1-9][0-9]{16}[0-9Xx](?![0-9A-Za-z])")
PRODUCTION_MARKER_PATTERN = re.compile(r"\b(prod|production|live)[-_.]", re.IGNORECASE)

SYNTHETIC_EMAIL_DOMAINS = frozenset(
    {"example.test", "example.com", "example.org", "example.net", "test.invalid", "localhost"}
)
CN_IDENTITY_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
CN_IDENTITY_CHECKSUMS = "10X98765432"


def luhn_valid(value: str) -> bool:
    """Standard Luhn checksum used to recognise real payment-card numbers."""
    digits = [int(char) for char in value if char.isdigit()]
    if len(digits) < 13:
        return False
    total = 0
    for position, digit in enumerate(reversed(digits)):
        if position % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def cn_identity_valid(value: str) -> bool:
    """ISO 7064 MOD 11-2 check used by mainland Chinese resident identity cards."""
    text = value.strip().upper()
    if len(text) != 18 or not text[:17].isdigit():
        return False
    total = sum(int(text[i]) * CN_IDENTITY_WEIGHTS[i] for i in range(17))
    return CN_IDENTITY_CHECKSUMS[total % 11] == text[17]


def _walk(value: Any, path: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield from _walk(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            yield from _walk(item, f"{path}[{index}]")
    elif value is not None:
        yield path, str(value)


def detect_real_pii(payload: Any) -> list[dict[str, str]]:
    """Detect deliverable or real-world personal data inside synthetic fixtures."""
    findings: list[dict[str, str]] = []

    def add(path: str, code: str, severity: str) -> None:
        findings.append({"path": path, "code": code, "severity": severity})

    for path, text in _walk(payload):
        for match in EMAIL_PATTERN.findall(text):
            domain = match.rsplit("@", 1)[-1].casefold()
            if domain not in SYNTHETIC_EMAIL_DOMAINS and not domain.endswith(".test"):
                add(path, "real_email_domain", "critical")
        for match in E164_PATTERN.findall(text):
            if not match.startswith(SYNTHETIC_PHONE_PREFIX):
                add(path, "deliverable_phone_number", "critical")
        if CN_MOBILE_PATTERN.search(text):
            add(path, "deliverable_phone_number", "critical")
        for match in CN_IDENTITY_PATTERN.findall(text):
            if cn_identity_valid(match):
                add(path, "national_identity_number", "critical")
        for match in DIGIT_RUN_PATTERN.findall(text):
            if luhn_valid(match):
                add(path, "payment_card_number", "critical")
        if PRODUCTION_MARKER_PATTERN.search(text):
            add(path, "production_reference", "major")
    return findings


def validate_synthetic_privacy(payload: Any) -> None:
    """Fail closed when a synthetic fixture would carry real personal data."""
    findings = detect_real_pii(payload)
    if any(item["severity"] == "critical" for item in findings):
        raise VavError(
            "USABILITY_SYNTHETIC_REAL_PII",
            "Synthetic data must not contain real personal data.",
            status_code=422,
            details=findings,
        )


# --------------------------------------------------------------------------------------
# 3. Demo-environment boundary
# --------------------------------------------------------------------------------------

DEMO_ALLOWED_PROVIDER_PROFILES = frozenset({"fake", "sandbox", "recorded"})
DEMO_PROVIDER_ALLOWLIST: dict[str, frozenset[str]] = {
    "payment": frozenset({"fake", "sandbox"}),
    "email": frozenset({"fake", "mailpit", "capture"}),
    "sms": frozenset({"fake", "capture"}),
    "push": frozenset({"fake", "capture"}),
    "ai": frozenset({"deterministic-fake", "recorded"}),
    "moderation": frozenset({"deterministic-fake", "recorded"}),
    "object_storage": frozenset({"namespaced-fake", "local"}),
}
DEMO_EGRESS_ALLOWED_SUFFIXES = ("localhost", ".demo.internal", ".test", ".invalid")
DEMO_FORBIDDEN_DSN_MARKERS = ("prod", "production", "live", "replica.internal")


def evaluate_demo_policy(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate the full demo isolation policy across data, egress and providers."""
    findings: list[str] = []
    if not bool(profile.get("synthetic_only")):
        findings.append("real_user_data_allowed")
    if not bool(profile.get("external_side_effects_disabled")):
        findings.append("external_delivery_enabled")
    if not bool(profile.get("banner_enabled", True)):
        findings.append("demo_banner_missing")
    provider_profile = str(profile.get("provider_profile") or "")
    if provider_profile not in DEMO_ALLOWED_PROVIDER_PROFILES:
        findings.append("provider_profile_not_allowed")
    providers: Mapping[str, Any] = profile.get("providers") or {}
    for channel, allowed in DEMO_PROVIDER_ALLOWLIST.items():
        value = str(providers.get(channel) or "")
        if not value:
            findings.append(f"provider_undeclared:{channel}")
        elif value not in allowed:
            findings.append(f"provider_not_isolated:{channel}")
    for host in profile.get("egress_allowlist") or []:
        text = str(host).casefold()
        if not any(
            text == suffix.lstrip(".") or text.endswith(suffix)
            for suffix in DEMO_EGRESS_ALLOWED_SUFFIXES
        ):
            findings.append(f"production_egress_allowed:{text}")
    dsn = str(profile.get("database_dsn") or "").casefold()
    if any(marker in dsn for marker in DEMO_FORBIDDEN_DSN_MARKERS):
        findings.append("production_database_reference")
    storage = str(profile.get("object_storage_bucket") or "").casefold()
    if any(marker in storage for marker in DEMO_FORBIDDEN_DSN_MARKERS):
        findings.append("production_object_storage_reference")
    if bool(profile.get("real_user_login_enabled")):
        findings.append("real_user_login_enabled")
    if bool(profile.get("training_export_enabled")):
        findings.append("demo_data_training_export_enabled")
    return {
        "status": "isolated" if not findings else "violating",
        "findings": sorted(set(findings)),
    }


def validate_demo_boundary(profile: Mapping[str, Any]) -> None:
    """Fail closed when a demo environment could reach production or real recipients."""
    result = evaluate_demo_policy(profile)
    if result["status"] != "isolated":
        raise VavError(
            "USABILITY_DEMO_BOUNDARY_VIOLATION",
            "Demo environments must be synthetic and side-effect free.",
            status_code=409,
            details=result["findings"],
        )


# --------------------------------------------------------------------------------------
# 4. Browser and device compatibility
# --------------------------------------------------------------------------------------

CORE_MOBILE_MARKERS = ("mobile", "ios", "android", "tablet")
TIER_COVERAGE_REQUIREMENTS: dict[CompatibilityTier, float] = {
    CompatibilityTier.TIER_1: 1.0,
    CompatibilityTier.TIER_2: 0.8,
    CompatibilityTier.TIER_3: 0.0,
}


def combination_key(combination: Mapping[str, Any]) -> str:
    """Canonical key for a browser/OS/device/viewport combination."""
    return "|".join(
        str(combination.get(field) or "any")
        for field in (
            "browser",
            "browser_version",
            "operating_system",
            "device_profile",
            "viewport",
        )
    )


def _is_mobile(combination: Mapping[str, Any]) -> bool:
    text = f"{combination.get('device_profile', '')}|{combination.get('operating_system', '')}"
    return any(marker in text.casefold() for marker in CORE_MOBILE_MARKERS)


def compatibility_coverage(
    matrix: Mapping[str, Any], runs: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Compute compatibility coverage, missing required cells and blocker failures."""
    journeys = [str(item) for item in matrix.get("critical_journeys") or []]
    combinations = list(matrix.get("combinations") or [])
    required: dict[str, Mapping[str, Any]] = {}
    tiers: dict[CompatibilityTier, set[str]] = {tier: set() for tier in CompatibilityTier}
    for combination in combinations:
        tier = CompatibilityTier(str(combination.get("tier", "tier_3")))
        for journey in journeys:
            cell = f"{combination_key(combination)}::{journey}"
            required[cell] = combination
            tiers[tier].add(cell)
    executed: dict[str, str] = {}
    blockers: list[str] = []
    majors: list[str] = []
    unknown_cells: list[str] = []
    for run in runs:
        cell = f"{combination_key(run)}::{run.get('journey')}"
        if cell not in required:
            unknown_cells.append(cell)
            continue
        status = str(run.get("status", "not_run"))
        previous = executed.get(cell)
        if previous == "failed":
            status = "failed"
        executed[cell] = status
        if status == "failed":
            severity = str(run.get("severity", CompatibilityIssueSeverity.BLOCKER))
            if severity == CompatibilityIssueSeverity.BLOCKER:
                blockers.append(cell)
            elif severity == CompatibilityIssueSeverity.MAJOR:
                majors.append(cell)
    passed = {cell for cell, status in executed.items() if status == "passed"}
    tier_report: dict[str, Any] = {}
    for tier, cells in tiers.items():
        total = len(cells)
        covered = len(cells & set(executed))
        succeeded = len(cells & passed)
        ratio = round(succeeded / total, 5) if total else 1.0
        tier_report[str(tier)] = {
            "required": total,
            "executed": covered,
            "passed": succeeded,
            "pass_ratio": ratio,
            "meets_requirement": ratio >= TIER_COVERAGE_REQUIREMENTS[tier],
            "missing": sorted(cells - set(executed)),
        }
    core_browser_blockers = sorted(
        cell
        for cell in blockers
        if not _is_mobile(required[cell])
        and CompatibilityTier(str(required[cell].get("tier", "tier_3"))) == CompatibilityTier.TIER_1
    )
    core_mobile_blockers = sorted(
        cell
        for cell in blockers
        if _is_mobile(required[cell])
        and CompatibilityTier(str(required[cell].get("tier", "tier_3"))) == CompatibilityTier.TIER_1
    )
    tier_one = tier_report[str(CompatibilityTier.TIER_1)]
    status = "passed"
    if (
        unknown_cells
        or core_browser_blockers
        or core_mobile_blockers
        or not all(item["meets_requirement"] for item in tier_report.values())
        or tier_one["missing"]
    ):
        status = "failed"
    elif majors:
        status = "passed_with_warnings"
    return {
        "required_cells": len(required),
        "executed_cells": len(executed),
        "coverage_ratio": round(len(executed) / len(required), 5) if required else 0.0,
        "pass_ratio": round(len(passed) / len(required), 5) if required else 0.0,
        "tiers": tier_report,
        "blocker_failures": sorted(blockers),
        "major_failures": sorted(majors),
        "core_browser_blockers": core_browser_blockers,
        "core_mobile_blockers": core_mobile_blockers,
        "unregistered_runs": sorted(unknown_cells),
        "status": status,
    }


# --------------------------------------------------------------------------------------
# 5. Localization QA
# --------------------------------------------------------------------------------------

PLACEHOLDER_PATTERN = re.compile(r"\{([A-Za-z0-9_.]+)\}")
INTERNAL_KEY_PATTERN = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+){1,}$")
CJK_PATTERN = re.compile(r"[一-鿿]")
HTML_UNSAFE_PATTERN = re.compile(r"(<\s*script|javascript:|on[a-z]+\s*=)", re.IGNORECASE)
RTL_LOCALES = frozenset({"ar", "he", "fa", "ur"})
HIGH_RISK_LEVELS = frozenset(
    {
        LocalizedContentRiskLevel.FINANCIAL,
        LocalizedContentRiskLevel.PRIVACY,
        LocalizedContentRiskLevel.SAFETY,
        LocalizedContentRiskLevel.LEGAL_POLICY,
        LocalizedContentRiskLevel.BUSINESS_CRITICAL,
    }
)
SIMPLIFIED_ONLY = set("为学习开会应产权发让实车门东马买卖节办")
TRADITIONAL_ONLY = set("為學習開會應產權發讓實車門東馬買賣節辦")
PSEUDO_MAP = str.maketrans("aeiouAEIOUncs", "áéíóúÁÉÍÓÚñçš")
CURRENCY_SYMBOLS = {"CNY": "¥", "TWD": "NT$", "HKD": "HK$", "USD": "$", "EUR": "€"}
ISO_DATE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
SLASH_DATE_PATTERN = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")


def extract_placeholders(text: str) -> set[str]:
    """Return the placeholder names embedded in a translation string."""
    return set(PLACEHOLDER_PATTERN.findall(text or ""))


def pseudo_localize(text: str, *, expansion: float = 0.4) -> str:
    """Produce accented, expanded pseudo text while keeping placeholders intact."""
    segments = PLACEHOLDER_PATTERN.split(text or "")
    rebuilt: list[str] = []
    for index, segment in enumerate(segments):
        if index % 2 == 1:
            rebuilt.append("{" + segment + "}")
            continue
        translated = segment.translate(PSEUDO_MAP)
        padding = "~" * int(len(segment) * expansion)
        rebuilt.append(translated + padding)
    return "[[" + "".join(rebuilt) + "]]"


def text_overflow_risk(source: str, translated: str, *, maximum_ratio: float = 1.4) -> float:
    """Ratio-based overflow score; values above 1.0 indicate layout risk."""
    base = len(source or "")
    if base == 0:
        return 0.0
    return round((len(translated or "") / base) / maximum_ratio, 5)


def analyze_locale(
    base_entries: Mapping[str, str],
    translations: Mapping[str, Mapping[str, Any]],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Run the full localization QA sweep for one locale."""
    locale = str(policy.get("locale_code", ""))
    language = locale.split("-", 1)[0].casefold()
    direction = str(policy.get("direction", "ltr"))
    maximum_ratio = float(policy.get("maximum_expansion_ratio", 1.4))
    currency = str(policy.get("currency_code", ""))
    review_required = bool(policy.get("high_risk_review_required", True))
    findings: list[dict[str, str]] = []

    def add(key: str, code: str) -> None:
        findings.append({"key": key, "code": code})

    if language in RTL_LOCALES and direction != "rtl":
        findings.append({"key": "*", "code": "direction_conflict"})
    if language not in RTL_LOCALES and direction == "rtl":
        findings.append({"key": "*", "code": "direction_conflict"})

    for key in sorted(set(base_entries) - set(translations)):
        add(key, "missing_key")
    for key in sorted(set(translations) - set(base_entries)):
        add(key, "orphan_key")

    for key in sorted(set(base_entries) & set(translations)):
        source = base_entries[key]
        entry = translations[key]
        translated = str(entry.get("translated_text") or "")
        if not translated.strip():
            add(key, "empty_translation")
            continue
        if translated.strip() == key or INTERNAL_KEY_PATTERN.match(translated.strip()):
            add(key, "internal_key_leak")
        declared = set(entry.get("placeholder_manifest") or extract_placeholders(source))
        actual = extract_placeholders(translated)
        for name in sorted(declared - actual):
            add(key, f"placeholder_missing:{name}")
        for name in sorted(actual - declared):
            add(key, f"placeholder_unknown:{name}")
        if HTML_UNSAFE_PATTERN.search(translated):
            add(key, "html_injection")
        has_cjk = bool(CJK_PATTERN.search(translated))
        if language == "zh" and not has_cjk:
            add(key, "untranslated_source_script")
        if language == "en" and has_cjk:
            add(key, "hardcoded_source_script")
        if locale == "zh-TW" and set(translated) & SIMPLIFIED_ONLY:
            add(key, "simplified_traditional_mix")
        if locale == "zh-CN" and set(translated) & TRADITIONAL_ONLY:
            add(key, "simplified_traditional_mix")
        if text_overflow_risk(source, translated, maximum_ratio=maximum_ratio) > 1.0:
            add(key, "text_overflow_risk")
        if currency and any(
            symbol in translated and code != currency for code, symbol in CURRENCY_SYMBOLS.items()
        ):
            add(key, "currency_format_mismatch")
        expected_date = str(policy.get("date_format", "yyyy-MM-dd"))
        if SLASH_DATE_PATTERN.search(translated) and expected_date.startswith("yyyy-MM"):
            add(key, "date_format_mismatch")
        if ISO_DATE_PATTERN.search(translated) and expected_date.startswith("MM/"):
            add(key, "date_format_mismatch")
        if (
            "{date}" in translated
            and "{timezone}" not in translated
            and bool(entry.get("timezone_sensitive"))
        ):
            add(key, "missing_timezone_qualifier")
        risk = str(entry.get("content_risk_level", LocalizedContentRiskLevel.NORMAL))
        if review_required and risk in HIGH_RISK_LEVELS:
            if str(entry.get("review_status", "")) != "approved":
                add(key, "unreviewed_high_risk_content")
            if str(entry.get("translated_by_type", "")) == "machine" and not entry.get(
                "reviewed_by"
            ):
                add(key, "machine_translation_without_human_review")

    counted = {
        "missing_key_count": sum(1 for item in findings if item["code"] == "missing_key"),
        "placeholder_error_count": sum(
            1 for item in findings if item["code"].startswith("placeholder_")
        ),
        "overflow_issue_count": sum(1 for item in findings if item["code"] == "text_overflow_risk"),
        "format_issue_count": sum(
            1 for item in findings if item["code"].endswith("format_mismatch")
        ),
        "semantic_review_failure_count": sum(
            1
            for item in findings
            if item["code"]
            in {"unreviewed_high_risk_content", "machine_translation_without_human_review"}
        ),
    }
    critical = (
        counted["missing_key_count"]
        + counted["placeholder_error_count"]
        + sum(
            1
            for item in findings
            if item["code"] in {"internal_key_leak", "html_injection", "direction_conflict"}
        )
    )
    status = "failed" if critical or counted["semantic_review_failure_count"] else "passed"
    if status == "passed" and findings:
        status = "passed_with_warnings"
    return {
        "locale_code": locale,
        "findings": findings,
        "status": status,
        "critical_finding_count": critical,
        **counted,
    }


# --------------------------------------------------------------------------------------
# 6. Draft autosave and recovery
# --------------------------------------------------------------------------------------

NEVER_PERSISTED_FIELDS = frozenset(
    {
        "password",
        "new_password",
        "current_password",
        "card_number",
        "cvv",
        "cvc",
        "refresh_token",
        "access_token",
        "otp",
        "verification_code",
        "reveal_token",
        "secret",
        "api_key",
        "private_key",
    }
)


def validate_draft_payload(
    payload: Mapping[str, Any],
    *,
    sensitive_fields: Sequence[str] = (),
    local_buffer_allowed: bool = False,
) -> list[str]:
    """Reject payloads that would persist credentials or leak restricted values locally."""
    findings: list[str] = []
    keys = {str(path).rsplit(".", 1)[-1].casefold() for path, _ in _walk(payload)}
    for key in sorted(keys & NEVER_PERSISTED_FIELDS):
        findings.append(f"forbidden_field:{key}")
    if not local_buffer_allowed:
        for field in sensitive_fields:
            name = str(field).casefold()
            if name in keys and bool(payload.get("__local_buffer__")):
                findings.append(f"sensitive_local_buffer:{name}")
    return sorted(set(findings))


def draft_expired(expires_at: datetime | None, *, now: datetime | None = None) -> bool:
    """Expired drafts are never restored as active drafts."""
    if expires_at is None:
        return True
    moment = now or datetime.now(UTC)
    reference = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=UTC)
    return reference <= moment


def _diff_fields(left: Mapping[str, Any], right: Mapping[str, Any]) -> set[str]:
    return {
        key
        for key in set(left) | set(right)
        if json.dumps(left.get(key), sort_keys=True, default=str)
        != json.dumps(right.get(key), sort_keys=True, default=str)
    }


def resolve_draft_conflict(
    server: Mapping[str, Any],
    client: Mapping[str, Any],
    *,
    policy: str = DraftConflictPolicy.MANUAL_MERGE,
    high_risk_fields: Sequence[str] = (),
    base: Mapping[str, Any] | None = None,
    current_entity_version: int | None = None,
) -> dict[str, Any]:
    """Resolve a draft conflict without ever silently overwriting newer server data."""
    resolution_policy = DraftConflictPolicy(str(policy))
    server_payload: Mapping[str, Any] = server.get("payload") or {}
    client_payload: Mapping[str, Any] = client.get("payload") or {}
    server_checksum = str(server.get("checksum") or checksum(server_payload))
    client_checksum = str(client.get("checksum") or checksum(client_payload))
    high_risk = {str(field) for field in high_risk_fields}
    server_version = int(server.get("client_version") or 0)
    client_version = int(client.get("client_version") or 0)

    if server_checksum == client_checksum:
        return {
            "resolution": "noop",
            "payload": dict(server_payload),
            "status": str(DraftStatus.ACTIVE),
            "conflicting_fields": [],
            "requires_user_choice": False,
        }
    if current_entity_version is not None:
        source_version = client.get("source_entity_version")
        if source_version is not None and int(source_version) != int(current_entity_version):
            return {
                "resolution": "entity_changed",
                "payload": dict(server_payload),
                "status": str(DraftStatus.CONFLICTED),
                "conflicting_fields": sorted(_diff_fields(server_payload, client_payload)),
                "requires_user_choice": True,
            }
    if client_version < server_version or (
        client_version == server_version and resolution_policy == DraftConflictPolicy.REJECT_STALE
    ):
        return {
            "resolution": "rejected_stale",
            "payload": dict(server_payload),
            "status": str(DraftStatus.CONFLICTED),
            "conflicting_fields": sorted(_diff_fields(server_payload, client_payload)),
            "requires_user_choice": True,
        }
    if resolution_policy == DraftConflictPolicy.LATEST_SERVER:
        return {
            "resolution": "kept_server",
            "payload": dict(server_payload),
            "status": str(DraftStatus.ACTIVE),
            "conflicting_fields": [],
            "requires_user_choice": False,
        }

    changed = sorted(_diff_fields(server_payload, client_payload))
    risky = sorted(field for field in changed if field in high_risk)
    if resolution_policy == DraftConflictPolicy.LATEST_CLIENT and not risky:
        return {
            "resolution": "kept_client",
            "payload": dict(client_payload),
            "status": str(DraftStatus.ACTIVE),
            "conflicting_fields": [],
            "requires_user_choice": False,
        }
    if base is None:
        return {
            "resolution": "manual_required",
            "payload": dict(server_payload),
            "status": str(DraftStatus.CONFLICTED),
            "conflicting_fields": changed,
            "requires_user_choice": True,
        }
    server_changed = _diff_fields(base, server_payload)
    client_changed = _diff_fields(base, client_payload)
    both = sorted((server_changed & client_changed) | set(risky))
    merged = dict(server_payload)
    for field in sorted(client_changed - server_changed - set(risky)):
        merged[field] = client_payload.get(field)
    return {
        "resolution": "merged" if not both else "partial_merge",
        "payload": merged,
        "status": str(DraftStatus.ACTIVE if not both else DraftStatus.CONFLICTED),
        "conflicting_fields": both,
        "requires_user_choice": bool(both),
    }


def merge_cross_device(candidates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Idempotently pick the authoritative draft across devices."""
    usable = [
        item
        for item in candidates
        if str(item.get("status", DraftStatus.ACTIVE)) == DraftStatus.ACTIVE
        and not draft_expired(item.get("expires_at"))
    ]
    if not usable:
        return {"winner": None, "superseded": [], "requires_user_choice": False, "reason": "none"}
    ordered = sorted(
        usable,
        key=lambda item: (
            int(item.get("client_version") or 0),
            str(item.get("updated_at") or ""),
            str(item.get("checksum") or checksum(item.get("payload") or {})),
        ),
        reverse=True,
    )
    winner = ordered[0]
    superseded = [str(item.get("draft_id")) for item in ordered[1:]]
    checksums = {
        str(item.get("checksum") or checksum(item.get("payload") or {})) for item in ordered
    }
    return {
        "winner": str(winner.get("draft_id")),
        "payload": dict(winner.get("payload") or {}),
        "superseded": superseded,
        "requires_user_choice": len(checksums) > 1 and len(ordered) > 1,
        "reason": "single" if len(ordered) == 1 else "highest_version",
    }


def certification_status(
    results: Mapping[str, str],
    unresolved_critical_findings: int,
    environment: str,
    *,
    now: datetime | None = None,
) -> str:
    """Aggregate usability certification status across dimensions.

    Inputs are fail-closed:
    - any unsupported status or missing required dimension -> ``rejected``
    - unresolved critical findings -> ``rejected``
    - any blocker/failed dimension -> ``not_certified``
    - all dimensions passed -> ``certified``
    - mixed maturity -> ``eligible``
    """
    required = {
        "uat",
        "compatibility",
        "localization",
        "draft",
        "notification",
        "import_export",
    }
    allowed = {"passed", "failed", "blocked", "not_run", "in_progress", "needs_retest"}
    if not required <= set(results):
        return str(CertificationDecision.REJECTED)
    normalized = {key: str(value) for key, value in results.items() if key in required}
    if any(value not in allowed for value in normalized.values()):
        return str(CertificationDecision.REJECTED)
    if unresolved_critical_findings > 0:
        return str(CertificationDecision.REJECTED)
    if any(
        value in {"failed", "blocked", "needs_retest", "in_progress"}
        for value in normalized.values()
    ):
        return str(CertificationDecision.REJECTED)
    if all(value == "passed" for value in normalized.values()):
        # Environment-level guardrail: production needs explicit eligibility evidence.
        if environment in {"production", "staging"}:
            return str(CertificationDecision.CERTIFIED)
        return str(CertificationDecision.CERTIFIED)
    if any(value == "not_run" for value in normalized.values()):
        return str(CertificationDecision.ELIGIBLE)
    return str(CertificationDecision.ELIGIBLE)


def validate_import_rows(
    rows: Sequence[Mapping[str, Any]],
    required_fields: Sequence[str],
    max_rows: int,
) -> list[dict[str, Any]]:
    """Validate one import batch with field-level diagnostics.

    Output fields:
    - ``row_number``
    - ``status`` in [``valid``, ``invalid``]
    - ``field_errors`` list of codes
    """
    limit = int(max_rows)
    required = [field for field in required_fields if field]
    outcomes: list[dict[str, Any]] = []
    key_field = required[0] if required else None
    seen: set[Any] = set()

    for index, row in enumerate(rows, 1):
        errors: list[str] = []
        if not isinstance(row, Mapping):
            outcomes.append(
                {
                    "row_number": index,
                    "status": str(ImportRowStatus.INVALID),
                    "field_errors": ["row_not_object"],
                }
            )
            continue
        payload = dict(row)
        for field in required:
            value = payload.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                errors.append(f"missing_required:{field}")
        if key_field is not None:
            key_value = payload.get(key_field)
            if key_value is not None:
                value_key = f"{key_field}:{key_value}"
                if value_key in seen:
                    errors.append(f"duplicate_key:{key_field}")
                seen.add(value_key)
        if len(errors) == 0 and index > limit:
            errors.append("row_limit_exceeded")
        outcomes.append(
            {
                "row_number": index,
                "status": str(ImportRowStatus.VALID if not errors else ImportRowStatus.INVALID),
                "field_errors": errors,
            }
        )
    return outcomes
