#!/usr/bin/env python3
"""Fail-closed intake and preflight for production certification gates.

The tool deliberately separates machine-verifiable readiness from facts that
must come from accountable humans or production systems. It never reads or
prints secret values: configuration contains environment-variable references
and evidence-file paths only.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "config/certification/external-gate-intake.yaml"
TEMPLATE = ROOT / "config/certification/external-gate-intake.template.yaml"
DEFAULT_REPORT = ROOT / "build/certification/external-gate-preflight.json"
DEFAULT_LOCK = ROOT / "build/certification/certification-target-lock.json"

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SCHEMA_VERSION = "1.0.0"


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _load(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"intake file does not exist: {path}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("intake document must be a mapping")
    return value


def _iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _result(name: str, findings: list[str], **details: Any) -> dict[str, Any]:
    return {
        "name": name,
        "status": "PASS" if not findings else "BLOCKED",
        "findings": sorted(set(findings)),
        **details,
    }


def _run(command: list[str], timeout: float = 10.0) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""
    return completed.returncode, (completed.stdout + completed.stderr).strip()


def _probe_url(url: str, timeout: float = 10.0) -> dict[str, Any]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, headers={"User-Agent": "vav-certification-intake/1"})
    try:
        with opener.open(request, timeout=timeout) as response:
            response.read(1024)
            return {"status_code": response.status, "ok": 200 <= response.status < 400}
    except urllib.error.HTTPError as exc:
        return {"status_code": exc.code, "ok": False}
    except (OSError, urllib.error.URLError) as exc:
        return {"status_code": None, "ok": False, "error": str(exc)}


def _evidence(
    raw: Any,
    *,
    field: str,
    base: Path,
    findings: list[str],
) -> dict[str, Any] | None:
    item = _mapping(raw)
    path_value = item.get("path")
    expected = str(item.get("sha256") or "")
    if not path_value:
        findings.append(f"{field}.path_missing")
        return None
    path = Path(str(path_value))
    if not path.is_absolute():
        path = base / path
    if not path.is_file():
        findings.append(f"{field}.file_missing")
        return None
    actual = _sha256_file(path)
    if expected != actual:
        findings.append(f"{field}.checksum_mismatch")
    return {"path": str(path), "sha256": actual}


def _env_reference(
    value: Any,
    *,
    field: str,
    findings: list[str],
    require_present: bool = True,
) -> str | None:
    name = str(value or "")
    if not ENV_RE.fullmatch(name):
        findings.append(f"{field}.invalid_env_reference")
        return None
    if require_present and not os.environ.get(name):
        findings.append(f"{field}.environment_variable_missing")
    return name


def validate_target(config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    findings: list[str] = []
    selection = config.get("certification_target")
    if selection not in {"current_production", "latest_feature"}:
        findings.append("certification_target.must_select_current_production_or_latest_feature")
    targets = _mapping(config.get("targets"))
    target = _mapping(targets.get(selection))
    if not target:
        findings.append("certification_target.definition_missing")

    for key in ("backend_git_commit", "frontend_git_commit"):
        if not SHA_RE.fullmatch(str(target.get(key) or "")):
            findings.append(f"target.{key}.invalid")
    for key in ("backend_deployment_id", "frontend_deployment_id", "release_version"):
        if not str(target.get(key) or "").strip():
            findings.append(f"target.{key}.missing")
    for key in ("api_url", "api_readiness_url", "user_url", "admin_url"):
        if not str(target.get(key) or "").startswith("https://"):
            findings.append(f"target.{key}.must_be_https")

    artifacts = _mapping(target.get("artifacts"))
    for name in ("backend", "frontend"):
        artifact = _mapping(artifacts.get(name))
        kind = artifact.get("kind")
        if kind not in {"source_deployment", "static_deployment", "oci_image"}:
            findings.append(f"target.artifacts.{name}.kind_invalid")
        if kind == "oci_image" and not DIGEST_RE.fullmatch(str(artifact.get("digest") or "")):
            findings.append(f"target.artifacts.{name}.digest_missing")
        if kind != "oci_image" and artifact.get("digest") not in {None, "", "not_applicable"}:
            findings.append(f"target.artifacts.{name}.non_oci_digest_must_be_not_applicable")

    normalized = {
        "schema_version": SCHEMA_VERSION,
        "selection": selection,
        "backend_git_commit": target.get("backend_git_commit"),
        "frontend_git_commit": target.get("frontend_git_commit"),
        "backend_deployment_id": target.get("backend_deployment_id"),
        "frontend_deployment_id": target.get("frontend_deployment_id"),
        "release_version": target.get("release_version"),
        "api_url": target.get("api_url"),
        "api_readiness_url": target.get("api_readiness_url"),
        "user_url": target.get("user_url"),
        "admin_url": target.get("admin_url"),
        "artifacts": artifacts,
    }
    fingerprint = _sha256_bytes(_canonical(normalized))
    normalized["target_fingerprint"] = fingerprint
    return normalized, _result("certification_target", findings, target_fingerprint=fingerprint)


def validate_security_authorization(
    config: dict[str, Any], *, base: Path, target: dict[str, Any], now: datetime
) -> dict[str, Any]:
    raw = _mapping(config.get("security_authorization"))
    findings: list[str] = []
    if raw.get("approved") is not True:
        findings.append("security_authorization.approved_missing")
    for key in ("authorization_id", "authorizing_owner", "owner_organization"):
        if not str(raw.get(key) or "").strip():
            findings.append(f"security_authorization.{key}_missing")
    starts = _iso(raw.get("starts_at"))
    ends = _iso(raw.get("ends_at"))
    if not starts or not ends or starts >= ends:
        findings.append("security_authorization.window_invalid")
    elif not starts <= now <= ends:
        findings.append("security_authorization.outside_approved_window")
    elif ends - starts > timedelta(hours=24):
        findings.append("security_authorization.window_exceeds_24_hours")

    scope = set(str(item) for item in _list(raw.get("target_urls")))
    required_urls = {str(target.get(key) or "") for key in ("api_url", "user_url", "admin_url")}
    if not required_urls.issubset(scope):
        findings.append("security_authorization.target_scope_incomplete")
    max_rps = raw.get("max_requests_per_second")
    max_concurrency = raw.get("max_concurrency")
    if not isinstance(max_rps, (int, float)) or not 0 < max_rps <= 10:
        findings.append("security_authorization.max_requests_per_second_outside_safe_cap")
    if not isinstance(max_concurrency, int) or not 0 < max_concurrency <= 10:
        findings.append("security_authorization.max_concurrency_outside_safe_cap")
    for cidr in _list(raw.get("source_ip_cidrs")):
        try:
            ipaddress.ip_network(str(cidr), strict=False)
        except ValueError:
            findings.append("security_authorization.source_ip_cidr_invalid")
    if not _list(raw.get("source_ip_cidrs")):
        findings.append("security_authorization.source_ip_cidrs_missing")

    forbidden = set(str(item) for item in _list(raw.get("forbidden_operations")))
    required_forbidden = {
        "denial_of_service",
        "destructive_data_mutation",
        "data_exfiltration",
        "persistence",
        "social_engineering",
    }
    if not required_forbidden.issubset(forbidden):
        findings.append("security_authorization.forbidden_operations_incomplete")
    if not _list(raw.get("allowed_test_types")):
        findings.append("security_authorization.allowed_test_types_missing")
    provider = _mapping(raw.get("independent_test_provider"))
    if not provider.get("organization") or not provider.get("lead_tester"):
        findings.append("security_authorization.independent_provider_missing")
    elif provider.get("organization") == raw.get("owner_organization"):
        findings.append("security_authorization.provider_not_independent")
    emergency = _mapping(raw.get("emergency_stop_contact"))
    if not emergency.get("name") or not emergency.get("contact"):
        findings.append("security_authorization.emergency_stop_contact_missing")
    evidence = _evidence(
        raw.get("written_authorization_evidence"),
        field="security_authorization.written_authorization_evidence",
        base=base,
        findings=findings,
    )
    return _result("security_authorization", findings, evidence=evidence)


def validate_accounts(
    config: dict[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    raw = _mapping(config.get("test_accounts"))
    current = now or datetime.now(UTC)
    findings: list[str] = []
    if raw.get("synthetic_data_only") is not True:
        findings.append("test_accounts.synthetic_data_only_required")
    if raw.get("contains_real_personal_data") is not False:
        findings.append("test_accounts.real_personal_data_must_be_false")
    accounts = [_mapping(item) for item in _list(raw.get("accounts"))]
    account_types = {str(item.get("type")) for item in accounts}
    for required in ("user", "admin"):
        if required not in account_types:
            findings.append(f"test_accounts.{required}_account_missing")
    safe_accounts: list[dict[str, Any]] = []
    for index, item in enumerate(accounts):
        prefix = f"test_accounts.accounts[{index}]"
        if item.get("type") not in {"user", "admin", "role_specific"}:
            findings.append(f"{prefix}.type_invalid")
        username_ref = _env_reference(
            item.get("username_env"), field=f"{prefix}.username", findings=findings
        )
        password_ref = _env_reference(
            item.get("password_env"), field=f"{prefix}.password", findings=findings
        )
        if not _list(item.get("roles")):
            findings.append(f"{prefix}.roles_missing")
        expiry = _iso(item.get("expires_at"))
        if not expiry:
            findings.append(f"{prefix}.expiry_invalid")
        elif expiry <= current:
            findings.append(f"{prefix}.already_expired")
        elif expiry - current > timedelta(days=30):
            findings.append(f"{prefix}.expiry_exceeds_30_days")
        safe_accounts.append(
            {
                "type": item.get("type"),
                "username_env": username_ref,
                "password_env": password_ref,
                "roles": _list(item.get("roles")),
                "expires_at": item.get("expires_at"),
            }
        )
    return _result("test_accounts", findings, accounts=safe_accounts)


def probe_devices() -> dict[str, Any]:
    ios_online: list[str] = []
    ios_offline: list[str] = []
    if shutil.which("xcrun"):
        _, output = _run(["xcrun", "xctrace", "list", "devices"])
        section = "online"
        for line in output.splitlines():
            stripped = line.strip()
            if stripped == "== Devices Offline ==":
                section = "offline"
                continue
            if stripped.startswith("== Simulators =="):
                section = "simulator"
                continue
            if section in {"online", "offline"} and stripped and "(" in stripped:
                if "MacBook" in stripped or stripped.startswith("=="):
                    continue
                (ios_online if section == "online" else ios_offline).append(stripped)

    android: list[str] = []
    if shutil.which("adb"):
        _, output = _run(["adb", "devices", "-l"])
        android = [
            line.strip()
            for line in output.splitlines()[1:]
            if " device " in f" {line} " and line.strip()
        ]
    return {
        "ios_physical_online": ios_online,
        "ios_physical_offline": ios_offline,
        "android_physical_online": android,
    }


def validate_devices(config: dict[str, Any], probe: dict[str, Any]) -> dict[str, Any]:
    raw = _mapping(config.get("device_uat"))
    findings: list[str] = []
    cloud = _mapping(raw.get("device_cloud"))
    cloud_configured = bool(cloud.get("provider"))
    if cloud_configured:
        _env_reference(
            cloud.get("credential_env"),
            field="device_uat.device_cloud.credential",
            findings=findings,
        )
    ios_ready = bool(probe.get("ios_physical_online")) or cloud_configured
    android_ready = bool(probe.get("android_physical_online")) or cloud_configured
    if raw.get("require_physical_ios") is True and not ios_ready:
        findings.append("device_uat.physical_ios_unavailable")
    if raw.get("require_physical_android") is True and not android_ready:
        findings.append("device_uat.physical_android_unavailable")
    if not _list(raw.get("required_journeys")):
        findings.append("device_uat.required_journeys_missing")
    return _result("device_uat", findings, probe=probe)


def validate_infrastructure(config: dict[str, Any], *, base: Path) -> dict[str, Any]:
    raw = _mapping(config.get("infrastructure_access"))
    findings: list[str] = []
    platform = raw.get("platform")
    if platform not in {"render_vercel", "kubernetes"}:
        findings.append("infrastructure_access.platform_invalid")

    if platform == "render_vercel":
        render = _mapping(raw.get("render"))
        if not render.get("service_id"):
            findings.append("infrastructure_access.render.service_id_missing")
        _env_reference(
            render.get("api_token_env"),
            field="infrastructure_access.render.api_token",
            findings=findings,
        )
    if platform == "kubernetes":
        kube = _mapping(raw.get("kubernetes"))
        _env_reference(
            kube.get("kubeconfig_env"),
            field="infrastructure_access.kubernetes.kubeconfig",
            findings=findings,
        )
        if not kube.get("production_context"):
            findings.append("infrastructure_access.kubernetes.production_context_missing")

    database = _mapping(raw.get("postgresql"))
    _env_reference(
        database.get("credential_env"),
        field="infrastructure_access.postgresql.credential",
        findings=findings,
    )
    required_db = {"pitr_restore", "replica_failover", "isolated_restore", "metrics_read"}
    if not required_db.issubset(set(_list(database.get("capabilities")))):
        findings.append("infrastructure_access.postgresql.capabilities_incomplete")

    storage = _mapping(raw.get("object_storage"))
    _env_reference(
        storage.get("credential_env"),
        field="infrastructure_access.object_storage.credential",
        findings=findings,
    )
    required_storage = {"backup_read", "isolated_restore", "inventory", "kms_decrypt"}
    if not required_storage.issubset(set(_list(storage.get("capabilities")))):
        findings.append("infrastructure_access.object_storage.capabilities_incomplete")

    redis = _mapping(raw.get("redis"))
    if redis.get("mode") == "disabled":
        if redis.get("not_applicable_approved") is not True:
            findings.append("infrastructure_access.redis.disabled_decision_not_approved")
        _evidence(
            redis.get("decision_evidence"),
            field="infrastructure_access.redis.decision_evidence",
            base=base,
            findings=findings,
        )
    else:
        _env_reference(
            redis.get("credential_env"),
            field="infrastructure_access.redis.credential",
            findings=findings,
        )
        if not {"failover", "queue_replay", "metrics_read"}.issubset(
            set(_list(redis.get("capabilities")))
        ):
            findings.append("infrastructure_access.redis.capabilities_incomplete")

    dr = _mapping(raw.get("regional_dr"))
    for key in ("secondary_region", "dns_failover_access", "load_balancer_access"):
        if not dr.get(key):
            findings.append(f"infrastructure_access.regional_dr.{key}_missing")
    return _result("infrastructure_access", findings, platform=platform)


def validate_approvals(
    config: dict[str, Any], *, base: Path, target_fingerprint: str
) -> dict[str, Any]:
    raw = _mapping(config.get("owner_approvals"))
    findings: list[str] = []
    approvals: list[dict[str, Any]] = []
    for role in ("production_owner", "security_owner", "data_governance_owner"):
        item = _mapping(raw.get(role))
        prefix = f"owner_approvals.{role}"
        if item.get("approved") is not True:
            findings.append(f"{prefix}.approval_missing")
        approver = str(item.get("approver") or "").strip()
        if len(approver) < 2:
            findings.append(f"{prefix}.real_name_missing")
        if not _iso(item.get("approved_at")):
            findings.append(f"{prefix}.approved_at_invalid")
        if item.get("target_fingerprint") != target_fingerprint:
            findings.append(f"{prefix}.target_fingerprint_mismatch")
        evidence = _evidence(
            item.get("evidence"), field=f"{prefix}.evidence", base=base, findings=findings
        )
        approvals.append(
            {
                "role": role,
                "approver": approver or None,
                "approved_at": item.get("approved_at"),
                "evidence": evidence,
            }
        )
    return _result("owner_approvals", findings, approvals=approvals)


def validate_load_authorization(
    config: dict[str, Any], *, base: Path, target: dict[str, Any], now: datetime
) -> dict[str, Any]:
    raw = _mapping(config.get("load_test_authorization"))
    findings: list[str] = []
    if raw.get("approved") is not True:
        findings.append("load_test_authorization.approved_missing")
    starts = _iso(raw.get("starts_at"))
    ends = _iso(raw.get("ends_at"))
    if not starts or not ends or starts >= ends:
        findings.append("load_test_authorization.window_invalid")
    elif not starts <= now <= ends:
        findings.append("load_test_authorization.outside_approved_window")
    if raw.get("target_url") != target.get("api_url"):
        findings.append("load_test_authorization.target_mismatch")
    if not isinstance(raw.get("max_concurrency"), int) or not 0 < raw["max_concurrency"] <= 100:
        findings.append("load_test_authorization.max_concurrency_invalid")
    if not isinstance(raw.get("max_requests_per_second"), (int, float)) or not (
        0 < raw["max_requests_per_second"] <= 100
    ):
        findings.append("load_test_authorization.max_requests_per_second_invalid")
    if not _mapping(raw.get("peak_model")):
        findings.append("load_test_authorization.peak_model_missing")
    else:
        peak = _mapping(raw.get("peak_model"))
        for key in (
            "expected_peak_concurrency",
            "expected_peak_requests_per_second",
            "duration_minutes",
        ):
            if not isinstance(peak.get(key), (int, float)) or peak[key] <= 0:
                findings.append(f"load_test_authorization.peak_model.{key}_invalid")
    contact = _mapping(raw.get("alert_contact"))
    if not contact.get("name") or not contact.get("contact"):
        findings.append("load_test_authorization.alert_contact_missing")
    _env_reference(
        raw.get("telemetry_access_env"),
        field="load_test_authorization.telemetry_access",
        findings=findings,
    )
    evidence = _evidence(
        raw.get("written_authorization_evidence"),
        field="load_test_authorization.written_authorization_evidence",
        base=base,
        findings=findings,
    )
    return _result("load_test_authorization", findings, evidence=evidence)


def preflight(config: dict[str, Any], *, source: Path, now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    target, target_result = validate_target(config)
    base = source.parent
    endpoints = {
        key: _probe_url(str(target[key]))
        for key in ("api_readiness_url", "user_url", "admin_url")
        if str(target.get(key) or "").startswith("https://")
    }
    endpoint_findings = [key for key, value in endpoints.items() if not value["ok"]]
    sections = [
        target_result,
        _result("production_endpoints", endpoint_findings, probes=endpoints),
        validate_security_authorization(config, base=base, target=target, now=current),
        validate_accounts(config, now=current),
        validate_devices(config, probe_devices()),
        validate_infrastructure(config, base=base),
        validate_approvals(
            config, base=base, target_fingerprint=str(target.get("target_fingerprint"))
        ),
        validate_load_authorization(config, base=base, target=target, now=current),
    ]
    blocked = [section["name"] for section in sections if section["status"] != "PASS"]
    return {
        "schema_version": SCHEMA_VERSION,
        "evaluated_at": current.isoformat(),
        "status": "READY_FOR_EXTERNAL_EXECUTION" if not blocked else "BLOCKED",
        "production_certification": False,
        "release_allowed": False,
        "target": target,
        "blocked_sections": blocked,
        "sections": sections,
        "note": (
            "READY_FOR_EXTERNAL_EXECUTION permits only the explicitly authorized runs. "
            "It is not production certification."
        ),
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="create an editable intake document")
    init_parser.add_argument("--output", type=Path, default=DEFAULT_INPUT)
    init_parser.add_argument("--force", action="store_true")

    lock_parser = subparsers.add_parser("lock-target", help="write immutable target identity")
    lock_parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    lock_parser.add_argument("--output", type=Path, default=DEFAULT_LOCK)

    check_parser = subparsers.add_parser("preflight", help="evaluate every external gate")
    check_parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    check_parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)

    args = parser.parse_args()
    if args.command == "init":
        if args.output.exists() and not args.force:
            print(f"refusing to overwrite {args.output}; pass --force", file=sys.stderr)
            return 2
        args.output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(TEMPLATE, args.output)
        print(args.output)
        return 0

    try:
        config = _load(args.input)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if config.get("schema_version") != SCHEMA_VERSION:
        print(f"schema_version must be {SCHEMA_VERSION}", file=sys.stderr)
        return 2

    if args.command == "lock-target":
        target, result = validate_target(config)
        payload = {
            "status": result["status"],
            "production_certification": False,
            "locked_at": datetime.now(UTC).isoformat(),
            **target,
        }
        _write_json(args.output, payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if result["status"] == "PASS" else 2

    report = preflight(config, source=args.input)
    _write_json(args.output, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "READY_FOR_EXTERNAL_EXECUTION" else 2


if __name__ == "__main__":
    raise SystemExit(main())
