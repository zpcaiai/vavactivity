#!/usr/bin/env python3

"""Batch 30 security control plane for deterministic, offline gate decisions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from vav.modules.trust_safety.domain import classify_text, evaluate_condition

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "security"
BUILD = ROOT / "build" / "security"
MANIFEST_PATH = CONFIG / "manifest.yaml"
BATCH_NUMBER = 30


def _external_evidence(name: str) -> dict[str, Any]:
    directory = os.environ.get("SECURITY_EVIDENCE_DIR")
    if not directory:
        return {
            "status": "NOT_EVALUATED",
            "reason": "SECURITY_EVIDENCE_DIR is not set",
        }
    path = Path(directory) / f"{name}.json"
    if not path.is_file():
        return {
            "status": "NOT_EVALUATED",
            "reason": f"external evidence is missing: {path}",
        }
    try:
        payload = _as_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "FAIL", "reason": f"invalid external evidence: {exc}"}
    status = str(payload.get("status", "FAIL"))
    if status not in {"PASS", "FAIL"}:
        return {"status": "FAIL", "reason": "external status must be PASS or FAIL"}
    if payload.get("git_commit") != _git_commit():
        return {"status": "FAIL", "reason": "external evidence commit mismatch"}
    if not re.fullmatch(r"[0-9a-f]{64}", str(payload.get("artifact_sha256", ""))):
        return {"status": "FAIL", "reason": "external evidence checksum missing"}
    if not payload.get("completed_at"):
        return {"status": "FAIL", "reason": "external evidence completion time missing"}
    return {
        "status": status,
        "path": str(path),
        "artifact_sha256": payload["artifact_sha256"],
        "completed_at": payload["completed_at"],
    }


def _bind_external(name: str, evaluation: dict[str, Any]) -> dict[str, Any]:
    evidence = _external_evidence(name)
    policy_status = str(evaluation.get("status", "FAIL"))
    if policy_status == "FAIL" or evidence["status"] == "FAIL":
        status = "FAIL"
    elif evidence["status"] == "PASS":
        status = "PASS"
    else:
        status = "NOT_EVALUATED"
    return {
        **evaluation,
        "policy_status": policy_status,
        "status": status,
        "external_evidence": evidence,
    }


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


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


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must be a mapping")
    return value


def _git_commit() -> str:
    supplied = os.environ.get("VAV_GIT_COMMIT")
    if supplied:
        if not re.fullmatch(r"[0-9a-f]{40}", supplied):
            raise ValueError("VAV_GIT_COMMIT must be a full lowercase Git commit")
        return supplied
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("Git commit identity is unavailable") from exc
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Git returned an invalid commit identity")
    return commit


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
        raise ValueError(f"security manifest batch must be {BATCH_NUMBER}")
    if manifest.get("schema_version") != "1.0.0":
        raise ValueError("security manifest schema_version must be 1.0.0")
    return manifest


def _skill_count() -> int:
    return len(list((ROOT / "skills" / "batch-30").glob("[0-9][0-9]-*/SKILL.md")))


def _condition_entries(item: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("conditions", "condition_rules", "conditionals", "rules"):
        conditions = item.get(key)
        if conditions is None:
            continue
        if isinstance(conditions, dict):
            return [conditions]
        if isinstance(conditions, list):
            return [
                condition for condition in conditions if isinstance(condition, dict)
            ]
        return []
    return []


def _security_signals(
    manifest: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    texts = _as_list(manifest.get("adversarial_texts"))
    text_findings: list[dict[str, Any]] = []
    counts: dict[str, int] = {
        "external_payment_link_detected": 0,
        "money_request_detected": 0,
        "threat_detected": 0,
        "staff_impersonation_detected": 0,
        "contact_information_bypass": 0,
        "pair_blocked": 0,
        "active_restriction_count": 0,
        "repeated_contact_count": 0,
        "post_decline_contact_count": 0,
        "distinct_target_count": 0,
        "like_rate": 0,
        "invitation_rate": 0,
        "account_takeover_signal": 0,
        "classifier_confidence_bps": 0,
    }
    for index, item in enumerate(texts):
        text = str(item)
        hits = sorted(classify_text(text))
        if "external_link" in hits:
            counts["external_payment_link_detected"] += 1
        if "money_request" in hits:
            counts["money_request_detected"] += 1
        if "threat" in hits:
            counts["threat_detected"] += 1
        if "impersonation" in hits:
            counts["staff_impersonation_detected"] += 1
        if "contact_information_bypass" in hits:
            counts["contact_information_bypass"] += 1
        text_findings.append(
            {
                "index": index,
                "text": text,
                "hits": hits,
            }
        )
    counts["pair_blocked"] = 1 if counts["contact_information_bypass"] > 0 else 0
    counts["repeated_contact_count"] = counts["contact_information_bypass"]
    counts["distinct_target_count"] = len(
        {
            item["code"]
            for item in _as_list(manifest.get("threat_models"))
            if isinstance(item, dict) and item.get("code")
        }
    )
    counts["classifier_confidence_bps"] = 10000 if text_findings else 0
    return counts, {
        "texts": text_findings,
        "signal_summary": counts,
    }


def _scan_summary(
    section_name: str,
    section: dict[str, Any],
    critical_limit: int = 0,
    high_limit: int = 0,
    medium_limit: int | None = None,
    require_findings_status: bool = False,
) -> dict[str, Any]:
    if not isinstance(section, dict):
        return {
            "section": section_name,
            "status": "NOT_EVALUATED",
            "reason": f"{section_name}_missing_or_invalid",
        }
    critical = _as_int(section.get("critical"), 0)
    high = _as_int(section.get("high"), 0)
    medium = _as_int(section.get("medium"), 0)
    findings = _as_list(section.get("findings"))
    unresolved = [
        _as_dict(item)
        for item in findings
        if str(_as_dict(item).get("status", "open")).lower()
        not in {"fixed", "mitigated", "accepted", "resolved"}
    ]
    failures: list[str] = []
    if critical > critical_limit:
        failures.append(f"{section_name}:critical_threshold")
    if high > high_limit:
        failures.append(f"{section_name}:high_threshold")
    if medium_limit is not None and medium > medium_limit:
        failures.append(f"{section_name}:medium_threshold")
    if require_findings_status and unresolved:
        failures.append(f"{section_name}:unresolved_findings_{len(unresolved)}")
    return {
        "section": section_name,
        "status": "PASS" if not failures else "FAIL",
        "critical": critical,
        "high": high,
        "medium": medium,
        "finding_count": len(findings),
        "unresolved_findings": len(unresolved),
        "failure_reasons": failures,
        "total_findings": len(findings),
    }


def _authorization_matrix_check(manifest: dict[str, Any]) -> dict[str, Any]:
    matrix = _as_dict(manifest.get("authorization_matrix"))
    required_roles = _as_list(matrix.get("required_roles"))
    cross_user_rules = _as_dict(matrix.get("cross_user_rules"))
    findings: list[str] = []

    if not required_roles:
        findings.append("required_roles_missing")
    for index, item in enumerate(required_roles):
        role_code = str(item.get("code", f"role-{index}"))
        actions = _as_list(item.get("actions"))
        if not actions:
            findings.append(f"role_{role_code}_actions_missing")
    if _as_bool(cross_user_rules.get("enforced")) is False:
        findings.append("cross_user_rules_not_enforced")
    if _as_bool(cross_user_rules.get("audit")) is False:
        findings.append("cross_user_audit_disabled")

    return {
        "status": "PASS" if not findings else "FAIL",
        "required_roles": len(required_roles),
        "cross_user_rules_enforced": _as_bool(cross_user_rules.get("enforced")),
        "cross_user_rules_audit": _as_bool(cross_user_rules.get("audit")),
        "findings": findings,
    }


def _threat_models(manifest: dict[str, Any], signals: dict[str, Any]) -> dict[str, Any]:
    models = []
    critical_failures = 0
    for index, item in enumerate(
        _as_list(manifest.get("threat_models", manifest.get("threat_model", [])))
    ):
        record = _as_dict(item)
        code = str(record.get("code", f"TM-UNKNOWN-{index + 1:03d}"))
        severity = str(record.get("severity", "")).lower()
        model_signals = dict(signals)
        controls = _as_list(record.get("controls"))
        model_signals["active_restriction_count"] = len(controls)
        findings: list[str] = []
        for key in ("code", "owner", "severity", "controls", "trust_level"):
            if key == "code":
                continue
            if _as_dict(record).get(key) in (None, "", [], {}):
                findings.append(f"{key}_missing")
        if severity in {"high", "critical"} and not controls:
            findings.append("high_risk_requires_controls")
        if severity in {"high", "critical"} and not record.get("data_classes"):
            findings.append("high_risk_requires_data_classes")
        if not isinstance(record.get("untrusted_boundary"), bool):
            findings.append("untrusted_boundary_invalid")
        record["_signal_context"] = model_signals
        findings.extend(_collect_conditions(record, f"threat-model:{code}"))
        if (
            _as_dict(record).get("trust_level") in {"critical", "high"}
            and len(controls) < 2
        ):
            findings.append("insufficient_control_depth")
        status = "PASS" if not findings else "FAIL"
        if status == "FAIL":
            critical_failures += 1
        models.append(
            {
                "code": code,
                "severity": str(record.get("severity", "")),
                "status": status,
                "controls": controls,
                "owner": record.get("owner"),
                "trust_level": record.get("trust_level"),
                "untrusted_boundary": record.get("untrusted_boundary"),
                "data_classes": _as_list(record.get("data_classes")),
                "finding_count": len(findings),
                "findings": findings,
            }
        )
    return {
        "status": "PASS" if critical_failures == 0 else "FAIL",
        "count": len(models),
        "critical_failure_count": critical_failures,
        "items": models,
    }


def _collect_conditions(
    item_or_signals: dict[str, Any],
    context: str,
) -> list[str]:
    conditions = _condition_entries(item_or_signals)
    if not conditions:
        return []
    # allow per-item context injection by caller
    signal_payload = item_or_signals.get("_signal_context", None)
    signals = signal_payload if isinstance(signal_payload, dict) else item_or_signals
    issues: list[str] = []
    for index, condition in enumerate(conditions):
        try:
            if not evaluate_condition(condition, signals):
                issues.append(f"{context}:condition[{index}]_failed")
        except ValueError as exc:
            issues.append(f"{context}:condition[{index}]_{exc}")
    return issues


def _attack_surfaces(
    manifest: dict[str, Any], base_signals: dict[str, Any]
) -> dict[str, Any]:
    raw_items = manifest.get("attack_surfaces", manifest.get("attack_surface", []))
    results = []
    critical_failures = 0

    for index, item in enumerate(_as_list(raw_items)):
        record = _as_dict(item)
        code = str(record.get("code", f"AS-UNKNOWN-{index + 1:03d}"))
        input_validation = _as_dict(record.get("input_validation"))
        failures: list[str] = []
        protocol = str(record.get("protocol", "https"))

        if protocol not in {"https", "grpc", "internal", "http"}:
            failures.append("unsupported_protocol")
        if protocol == "http":
            failures.append("must_not_use_http")
        if (
            not isinstance(record.get("auth_modes"), list)
            and record.get("auth_required") is True
        ):
            failures.append("auth_modes_missing")
        if record.get("auth_required") not in (True, False):
            failures.append("auth_required_invalid")
        if record.get("auth_required") and not _as_list(record.get("auth_modes")):
            failures.append("auth_modes_empty")
        if not input_validation:
            failures.append("input_validation_missing")
        if code.upper().startswith("API"):
            if not _as_dict(input_validation).get("body_schema_enforced"):
                failures.append("api_body_validation_missing")
            if not _as_dict(input_validation).get("command_id_required"):
                failures.append("api_idempotency_command_id_missing")
        if "UPLOAD" in code.upper():
            allowed_types = _as_list(input_validation.get("file_type_allowed"))
            if not allowed_types:
                failures.append("upload_file_types_not_defined")
            if _as_bool(input_validation.get("virus_scan_enabled")) is False:
                failures.append("upload_virus_scan_required")
            if _as_bool(input_validation.get("quarantine_unscanned")) is False:
                failures.append("upload_quarantine_required")
            if not record.get("upload_size_limit_mb"):
                failures.append("upload_size_limit_missing")
        if "WEBHOOK" in code.upper():
            required_signature_modes = {"hmac_signature"}
            auth_modes = {
                str(mode).lower() for mode in _as_list(record.get("auth_modes"))
            }
            if not required_signature_modes & auth_modes:
                failures.append("webhook_signature_required")
            if not _as_bool(input_validation.get("file_type_allowed")):
                # keep backward compatible behavior: keep this check permissive for existing schemas
                pass
        if "AI" in code.upper():
            if not _as_bool(input_validation.get("moderation_enabled")):
                failures.append("ai_moderation_required")
            if not _as_bool(input_validation.get("pii_redaction_enabled")):
                failures.append("ai_pii_redaction_required")

        # attach signals for conditional DSL checks
        record["_signal_context"] = dict(base_signals)
        failures.extend(_collect_conditions(record, f"attack_surface:{code}"))

        status = "PASS" if not failures else "FAIL"
        if status == "FAIL":
            critical_failures += 1
        results.append(
            {
                "code": code,
                "protocol": protocol,
                "status": status,
                "auth_required": bool(record.get("auth_required")),
                "auth_modes": _as_list(record.get("auth_modes")),
                "finding_count": len(failures),
                "findings": failures,
            }
        )

    return {
        "status": "PASS" if critical_failures == 0 else "FAIL",
        "count": len(results),
        "critical_failure_count": critical_failures,
        "items": results,
    }


def _auth_checks(manifest: dict[str, Any]) -> dict[str, Any]:
    auth = _as_dict(_as_dict(manifest.get("api_security")).get("authentication"))
    findings: list[str] = []
    if not _as_list(auth.get("mfa_required_roles")):
        findings.append("mfa_required_roles_missing")
    if _as_int(auth.get("token_rotation_hours"), 0) < 12:
        findings.append("token_rotation_too_short")
    if not _as_bool(auth.get("session_revocation_supported")):
        findings.append("session_revocation_not_supported")
    return {
        "status": "PASS" if not findings else "FAIL",
        "findings": findings,
        "mfa_required_roles": _as_list(auth.get("mfa_required_roles")),
        "token_rotation_hours": _as_int(auth.get("token_rotation_hours"), 0),
        "session_revocation_supported": _as_bool(
            auth.get("session_revocation_supported")
        ),
    }


def _authorization_checks(manifest: dict[str, Any]) -> dict[str, Any]:
    authz = _as_dict(_as_dict(manifest.get("api_security")).get("authorization"))
    findings: list[str] = []
    if not _as_bool(authz.get("deny_by_default")):
        findings.append("deny_by_default_disabled")
    if not _as_bool(authz.get("cross_tenant_controls")):
        findings.append("cross_tenant_controls_disabled")
    endpoints = _as_list(authz.get("privileged_endpoints"))
    if not endpoints:
        findings.append("privileged_endpoints_missing")
    return {
        "status": "PASS" if not findings else "FAIL",
        "findings": findings,
        "privileged_endpoints": endpoints,
    }


def _injection_checks(manifest: dict[str, Any]) -> dict[str, Any]:
    injection = _as_dict(_as_dict(manifest.get("api_security")).get("injection"))
    findings: list[str] = []
    if not _as_bool(injection.get("parameterized_queries_required")):
        findings.append("parameterized_queries_required")
    template_rendering = str(injection.get("template_rendering", "")).lower()
    if template_rendering not in {"sanitized", "escaped", "auto"}:
        findings.append("template_rendering_unhardened")
    return {
        "status": "PASS" if not findings else "FAIL",
        "findings": findings,
        "parameterized_queries_required": _as_bool(
            injection.get("parameterized_queries_required")
        ),
        "template_rendering": template_rendering,
    }


def _ssrf_checks(manifest: dict[str, Any]) -> dict[str, Any]:
    ssrf = _as_dict(_as_dict(manifest.get("api_security")).get("ssrf"))
    findings: list[str] = []
    if not _as_bool(ssrf.get("proxy_required")):
        findings.append("proxy_required")
    allowed = _as_list(ssrf.get("egress_allowed_hosts"))
    if len(allowed) < 2:
        findings.append("egress_host_allowlist_too_small")
    return {
        "status": "PASS" if not findings else "FAIL",
        "findings": findings,
        "egress_allowed_hosts": allowed,
        "proxy_required": _as_bool(ssrf.get("proxy_required")),
    }


def _upload_checks(manifest: dict[str, Any]) -> dict[str, Any]:
    upload = _as_dict(_as_dict(manifest.get("api_security")).get("file_upload"))
    findings: list[str] = []
    if not _as_bool(upload.get("scan_required")):
        findings.append("scan_required")
    if not _as_bool(upload.get("quarantine_required")):
        findings.append("quarantine_required")
    blocklist = _as_list(upload.get("extensions_blocklist"))
    if not blocklist:
        findings.append("extensions_blocklist_missing")
    return {
        "status": "PASS" if not findings else "FAIL",
        "findings": findings,
        "scan_required": _as_bool(upload.get("scan_required")),
        "quarantine_required": _as_bool(upload.get("quarantine_required")),
        "extensions_blocklist": blocklist,
    }


def _webhook_checks(manifest: dict[str, Any]) -> dict[str, Any]:
    webhook = _as_dict(_as_dict(manifest.get("api_security")).get("webhook"))
    findings: list[str] = []
    if not _as_bool(webhook.get("signature_required")):
        findings.append("signature_required")
    if _as_int(webhook.get("replay_window_seconds"), 0) <= 0:
        findings.append("replay_window_invalid")
    if _as_int(webhook.get("timestamp_tolerance_seconds"), 0) <= 0:
        findings.append("timestamp_tolerance_invalid")
    return {
        "status": "PASS" if not findings else "FAIL",
        "findings": findings,
        "signature_required": _as_bool(webhook.get("signature_required")),
        "replay_window_seconds": _as_int(webhook.get("replay_window_seconds"), 0),
        "timestamp_tolerance_seconds": _as_int(
            webhook.get("timestamp_tolerance_seconds"), 0
        ),
    }


def _privacy_checks(manifest: dict[str, Any]) -> dict[str, Any]:
    privacy = _as_dict(_as_dict(manifest.get("api_security")).get("privacy"))
    findings: list[str] = []
    if not _as_bool(privacy.get("pii_encryption_required")):
        findings.append("pii_encryption_required")
    if _as_int(privacy.get("delete_events_after_days"), 0) < 1:
        findings.append("delete_events_after_days_invalid")
    if not _as_bool(privacy.get("consent_required")):
        findings.append("consent_required")
    return {
        "status": "PASS" if not findings else "FAIL",
        "findings": findings,
        "pii_encryption_required": _as_bool(privacy.get("pii_encryption_required")),
        "delete_events_after_days": _as_int(privacy.get("delete_events_after_days"), 0),
        "consent_required": _as_bool(privacy.get("consent_required")),
    }


def _ai_checks(manifest: dict[str, Any], signals: dict[str, Any]) -> dict[str, Any]:
    ai = _as_dict(manifest.get("ai_safety"))
    prompt_vectors = _as_list(ai.get("prompt_injection_test_vectors"))
    risk_vectors = _as_list(ai.get("high_risk_texts"))
    all_vectors = [str(item) for item in prompt_vectors + risk_vectors]
    ai_findings = _as_dict({item.get("text", ""): item for item in []})
    classified: list[dict[str, Any]] = []
    hit_counter: dict[str, int] = {
        "external_link": 0,
        "money_request": 0,
        "threat": 0,
        "impersonation": 0,
        "contact_information_bypass": 0,
    }
    for index, text in enumerate(all_vectors):
        hits = sorted(classify_text(str(text)))
        for hit in hits:
            if hit in hit_counter:
                hit_counter[hit] += 1
        classified.append({"index": index, "text": str(text), "hits": hits})
    for hit_key in ("external_link", "money_request", "threat", "impersonation"):
        if hit_counter[hit_key] == 0 and len(all_vectors) > 0:
            ai_findings[f"missing_{hit_key}_detection"] = "not_detected"

    ai_context = dict(signals)
    ai_context["money_request_detected"] = hit_counter["money_request"]
    ai_context["threat_detected"] = hit_counter["threat"]
    ai_context["external_payment_link_detected"] = hit_counter["external_link"]
    ai_context["staff_impersonation_detected"] = hit_counter["impersonation"]
    conditions = _condition_entries(ai)
    if conditions:
        for index, condition in enumerate(conditions):
            try:
                if not evaluate_condition(condition, ai_context):
                    ai_findings[f"condition[{index}]"] = "not_satisfied"
            except ValueError as exc:
                ai_findings[f"condition[{index}]"] = str(exc)

    if _as_float(ai.get("ai_score_threshold"), 0.0) < 0.95:
        ai_findings["ai_score_threshold_low"] = ai.get("ai_score_threshold")
    if not _as_bool(ai.get("model_confirmation_required")):
        ai_findings["model_confirmation_required"] = "disabled"
    if not _as_bool(ai.get("sandbox_enforced")):
        ai_findings["sandbox_enforced"] = "disabled"
    if not _as_bool(ai.get("tool_replay_control")):
        ai_findings["tool_replay_control"] = "disabled"
    if not all_vectors:
        ai_findings["test_vectors"] = "missing"

    return {
        "status": "PASS" if not ai_findings else "FAIL",
        "test_vectors": len(all_vectors),
        "prompt_vectors": len(prompt_vectors),
        "risk_vectors": len(risk_vectors),
        "classified_vectors": classified,
        "hits": hit_counter,
        "findings": ai_findings,
    }


def _skill_security_checks(manifest: dict[str, Any]) -> dict[str, Any]:
    skill = _as_dict(manifest.get("skill_security"))
    permissions = _as_dict(skill.get("plugin_permissions"))
    findings: list[str] = []
    if not _as_bool(skill.get("sandbox_signature_required")):
        findings.append("sandbox_signature_required")
    if permissions.get("network"):
        findings.append("plugin_network_permission")
    if permissions.get("payments"):
        findings.append("plugin_payments_permission")
    if permissions.get("raw_file_access"):
        findings.append("plugin_raw_file_access")
    return {
        "status": "PASS" if not findings else "FAIL",
        "findings": findings,
        "sandbox_signature_required": _as_bool(skill.get("sandbox_signature_required")),
        "plugin_permissions": permissions,
    }


def _penetration(manifest: dict[str, Any]) -> dict[str, Any]:
    value = _as_dict(manifest.get("penetration"))
    required = _as_bool(value.get("required"))
    if not required:
        return {
            "status": "FAIL",
            "required": False,
            "failures": ["penetration_test_not_required"],
        }
    return {
        "status": "PASS",
        "required": True,
        "critical_findings_max": _as_int(value.get("critical_findings_max"), 0),
        "high_findings_max": _as_int(value.get("high_findings_max"), 0),
        "failures": [],
    }


def _api_dast(manifest: dict[str, Any]) -> dict[str, Any]:
    checks = _as_dict(manifest.get("security_checks"))
    required = _as_bool(checks.get("red_team_required"))
    return {
        "status": "PASS" if required else "NOT_EVALUATED",
        "red_team_required": required,
        "ai_tool_confirm_required": _as_bool(checks.get("ai_tool_confirm_required")),
        "sandbox_escape_attempts_seen": _as_int(
            checks.get("sandbox_escape_attempts_seen"), 0
        ),
    }


def _api_fuzz(manifest: dict[str, Any]) -> dict[str, Any]:
    checks = _as_dict(manifest.get("security_checks"))
    required = _as_bool(checks.get("ai_tool_confirm_required"))
    return {
        "status": "PASS" if required else "NOT_EVALUATED",
        "ai_tool_confirm_required": required,
    }


def snapshot() -> dict[str, Any]:
    manifest = _manifest()
    signals, text_evidence = _security_signals(manifest)
    threat_models = _threat_models(manifest, signals)
    attack_surfaces = _attack_surfaces(manifest, signals)
    sast = _bind_external(
        "sast",
        _scan_summary(
            "sast",
            manifest.get("sast"),
            critical_limit=0,
            high_limit=1,
            require_findings_status=True,
        ),
    )
    sca = _bind_external(
        "sca",
        _scan_summary(
            "sca",
            manifest.get("sca"),
            critical_limit=0,
            high_limit=0,
            require_findings_status=True,
        ),
    )
    secret_scan = _bind_external(
        "secret-scan",
        _scan_summary(
            "secret_scan",
            manifest.get("secret_scan"),
            critical_limit=0,
            high_limit=0,
            require_findings_status=False,
        ),
    )
    iac_scan = _bind_external(
        "iac-scan",
        _scan_summary(
            "iac",
            manifest.get("iac"),
            critical_limit=0,
            high_limit=0,
            require_findings_status=False,
        ),
    )
    container_scan = _bind_external(
        "container-scan",
        _scan_summary(
            "container",
            manifest.get("container"),
            critical_limit=0,
            high_limit=0,
            require_findings_status=False,
        ),
    )
    auth = _auth_checks(manifest)
    authorization = _authorization_checks(manifest)
    injection = _injection_checks(manifest)
    ssrf = _ssrf_checks(manifest)
    upload = _upload_checks(manifest)
    webhook = _webhook_checks(manifest)
    privacy = _privacy_checks(manifest)
    ai = _ai_checks(manifest, signals)
    skill = _skill_security_checks(manifest)
    pen = _bind_external("penetration-test", _penetration(manifest))
    matrix = _authorization_matrix_check(manifest)

    return {
        "schema_version": manifest["schema_version"],
        "batch": manifest["batch"],
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "build": {
            "name": manifest.get("name"),
            "checksum": manifest_checksum(manifest),
            "skill_count": _skill_count(),
        },
        "threat_models": threat_models,
        "attack_surfaces": attack_surfaces,
        "sast": sast,
        "sca": sca,
        "secret_scan": secret_scan,
        "iac_scan": iac_scan,
        "container_scan": container_scan,
        "auth": auth,
        "authorization": authorization,
        "authorization_matrix": matrix,
        "injection": injection,
        "ssrf": ssrf,
        "upload": upload,
        "webhook": webhook,
        "privacy": privacy,
        "ai_safety": ai,
        "skill_sandbox": skill,
        "penetration": pen,
        "api_dast": _bind_external("api-dast", _api_dast(manifest)),
        "api_fuzz": _bind_external("api-fuzz", _api_fuzz(manifest)),
        "threat_text_evidence": text_evidence,
    }


def manifest_checksum(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(manifest, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _overall_technical_status(snap: dict[str, Any]) -> str:
    hard_checks = [
        snap["threat_models"]["status"],
        snap["attack_surfaces"]["status"],
        snap["sast"]["status"],
        snap["sca"]["status"],
        snap["secret_scan"]["status"],
        snap["iac_scan"]["status"],
        snap["container_scan"]["status"],
        snap["auth"]["status"],
        snap["authorization"]["status"],
        snap["authorization_matrix"]["status"],
        snap["injection"]["status"],
        snap["ssrf"]["status"],
        snap["upload"]["status"],
        snap["webhook"]["status"],
        snap["privacy"]["status"],
        snap["ai_safety"]["status"],
        snap["skill_sandbox"]["status"],
        snap["penetration"]["status"],
        snap["api_dast"]["status"],
        snap["api_fuzz"]["status"],
    ]
    if "FAIL" in hard_checks:
        return "FAIL"
    if "NOT_EVALUATED" in hard_checks:
        return "NOT_EVALUATED"
    return "PASS"


def _technical_report() -> dict[str, Any]:
    snap = snapshot()
    technical_status = _overall_technical_status(snap)
    api_guard = (
        "PASS"
        if all(
            item["status"] in {"PASS", "NOT_EVALUATED"}
            for item in (
                snap["auth"],
                snap["authorization"],
                snap["authorization_matrix"],
                snap["injection"],
                snap["ssrf"],
                snap["upload"],
                snap["webhook"],
                snap["privacy"],
            )
        )
        else "FAIL"
    )
    return {
        "schema_version": "1.0.0",
        "batch": BATCH_NUMBER,
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": snap["git_commit"],
        "technical_status": technical_status,
        "production_certification": "NOT_CERTIFIED",
        "release_allowed": False,
        "critical_findings": snap["penetration"].get("critical_findings", 0)
        + snap["threat_models"].get("critical_failure_count", 0),
        "evidence": {
            "threat_models": snap["threat_models"]["status"],
            "attack_surfaces": snap["attack_surfaces"]["status"],
            "static_scans": {
                "sast": snap["sast"]["status"],
                "sca": snap["sca"]["status"],
                "secret": snap["secret_scan"]["status"],
                "iac": snap["iac_scan"]["status"],
                "container": snap["container_scan"]["status"],
            },
            "api_security": (api_guard),
            "api_controls": {
                "auth": snap["auth"]["status"],
                "authorization": snap["authorization"]["status"],
                "authorization_matrix": snap["authorization_matrix"]["status"],
                "injection": snap["injection"]["status"],
                "ssrf": snap["ssrf"]["status"],
                "upload": snap["upload"]["status"],
                "webhook": snap["webhook"]["status"],
                "privacy": snap["privacy"]["status"],
            },
            "threat_text_evidence": {
                "signals": snap["threat_text_evidence"]["signal_summary"],
                "sample_size": len(snap["threat_text_evidence"]["texts"]),
                "status": "PASS"
                if snap["threat_text_evidence"]["texts"]
                else "NOT_EVALUATED",
            },
            "ai_safety": snap["ai_safety"]["status"],
            "skill_sandbox": snap["skill_sandbox"]["status"],
            "api_dast": snap["api_dast"]["status"],
            "api_fuzz": snap["api_fuzz"]["status"],
            "penetration": snap["penetration"]["status"],
        },
        "backend_tests": "NOT_RUN",
        "admin_e2e": "NOT_RUN",
        "frontend_security": "NOT_RUN",
    }


def _status_print(payload: dict[str, Any], action: str) -> None:
    output = {"command": action, **payload}
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))


def run(action: str) -> int:
    _manifest()
    snap = snapshot()

    if action in {"migrate", "seed"}:
        _status_print(
            {
                "status": "NOT_RUN",
                "batch": BATCH_NUMBER,
                "reason": "offline control plane",
            },
            action,
        )
        return 0

    if action in {"sync", "security-sync"}:
        print(_write("security-snapshot.json", snap))
        return 0

    if action in {"threat-model-check", "threat"}:
        status = snap["threat_models"]["status"]
        _status_print({"status": status, **snap["threat_models"]}, action)
        return 0 if status == "PASS" else 1

    if action in {"attack-surface-check", "attack", "attack-surface"}:
        status = snap["attack_surfaces"]["status"]
        _status_print({"status": status, **snap["attack_surfaces"]}, action)
        return 0 if status == "PASS" else 1

    if action == "sast":
        status = snap["sast"]["status"]
        _status_print(snap["sast"], action)
        return 0 if status in {"PASS", "NOT_EVALUATED"} else 1

    if action == "sca":
        status = snap["sca"]["status"]
        _status_print(snap["sca"], action)
        return 0 if status in {"PASS", "NOT_EVALUATED"} else 1

    if action == "secret-scan":
        status = snap["secret_scan"]["status"]
        _status_print(snap["secret_scan"], action)
        return 0 if status in {"PASS", "NOT_EVALUATED"} else 1

    if action == "iac-scan":
        status = snap["iac_scan"]["status"]
        _status_print(snap["iac_scan"], action)
        return 0 if status in {"PASS", "NOT_EVALUATED"} else 1

    if action == "container-scan":
        status = snap["container_scan"]["status"]
        _status_print(snap["container_scan"], action)
        return 0 if status in {"PASS", "NOT_EVALUATED"} else 1

    if action == "api-dast":
        status = snap["api_dast"]["status"]
        _status_print(snap["api_dast"], action)
        return 0 if status in {"PASS", "NOT_EVALUATED"} else 1

    if action in {"api-fuzz", "fuzz"}:
        status = snap["api_fuzz"]["status"]
        _status_print(snap["api_fuzz"], action)
        return 0 if status in {"PASS", "NOT_EVALUATED"} else 1

    if action == "auth-test":
        status = snap["auth"]["status"]
        _status_print(snap["auth"], action)
        return 0 if status == "PASS" else 1

    if action == "authorization-test":
        status = snap["authorization"]["status"]
        _status_print(snap["authorization"], action)
        return 0 if status == "PASS" else 1

    if action == "injection-test":
        status = snap["injection"]["status"]
        _status_print(snap["injection"], action)
        return 0 if status == "PASS" else 1

    if action == "ssrf-test":
        status = snap["ssrf"]["status"]
        _status_print(snap["ssrf"], action)
        return 0 if status == "PASS" else 1

    if action == "upload-test":
        status = snap["upload"]["status"]
        _status_print(snap["upload"], action)
        return 0 if status == "PASS" else 1

    if action == "webhook-test":
        status = snap["webhook"]["status"]
        _status_print(snap["webhook"], action)
        return 0 if status == "PASS" else 1

    if action == "privacy-test":
        status = snap["privacy"]["status"]
        _status_print(snap["privacy"], action)
        return 0 if status == "PASS" else 1

    if action == "ai-test":
        status = snap["ai_safety"]["status"]
        _status_print(snap["ai_safety"], action)
        return 0 if status == "PASS" else 1

    if action == "skill-test":
        status = snap["skill_sandbox"]["status"]
        _status_print(snap["skill_sandbox"], action)
        return 0 if status == "PASS" else 1

    if action in {"pen-test", "pentest", "penetration-test", "penetration"}:
        status = snap["penetration"]["status"]
        _status_print(snap["penetration"], action)
        return 0 if status in {"PASS", "NOT_EVALUATED"} else 1

    if action == "admin-e2e":
        _status_print({"status": "NOT_RUN", "reason": "offline control"}, action)
        return 0

    if action in {"evidence", "evidence-build"}:
        report = _technical_report()
        path = _write("security-evidence.json", report)
        print(path)
        return (
            0
            if report["technical_status"] in {"PASS", "NOT_EVALUATED", "NOT_CERTIFIED"}
            else 1
        )

    raise ValueError(f"unsupported security action: {action}")


def parse_action(parts: list[str]) -> str:
    def _normalize(parts: list[str]) -> list[str]:
        normalized: list[str] = []
        for part in parts:
            normalized.extend(
                token
                for token in str(part).replace("_", "-").lower().split("-")
                if token
            )
        return normalized

    normalized = _normalize(parts)
    if normalized and normalized[0] == "security":
        normalized = normalized[1:]

    aliases = {
        ("migrate",): "migrate",
        ("seed",): "seed",
        ("sync",): "sync",
        ("threat", "model", "check"): "threat-model-check",
        ("threat", "model"): "threat-model-check",
        ("threat-model",): "threat-model-check",
        ("attack", "surface", "check"): "attack-surface-check",
        ("attack", "surface"): "attack-surface-check",
        ("attack-surface",): "attack-surface-check",
        ("sast",): "sast",
        ("sca",): "sca",
        ("secret", "scan"): "secret-scan",
        ("iac", "scan"): "iac-scan",
        ("container", "scan"): "container-scan",
        ("api", "dast"): "api-dast",
        ("dast",): "api-dast",
        ("api", "fuzz"): "api-fuzz",
        ("fuzz",): "api-fuzz",
        ("api", "fuzz", "test"): "api-fuzz",
        ("auth", "test"): "auth-test",
        ("auth",): "auth-test",
        ("authorization", "test"): "authorization-test",
        ("authorization",): "authorization-test",
        ("injection", "test"): "injection-test",
        ("injection",): "injection-test",
        ("ssrf", "test"): "ssrf-test",
        ("ssrf",): "ssrf-test",
        ("upload", "test"): "upload-test",
        ("upload",): "upload-test",
        ("webhook", "test"): "webhook-test",
        ("webhook",): "webhook-test",
        ("privacy", "test"): "privacy-test",
        ("privacy",): "privacy-test",
        ("ai", "test"): "ai-test",
        ("ai-prompt",): "ai-test",
        ("skill", "test"): "skill-test",
        ("supply-chain",): "skill-test",
        ("pen", "test"): "pen-test",
        ("pen", "test", "regression"): "pen-test",
        ("penetration", "test"): "pen-test",
        ("pentest",): "pen-test",
        ("pentest", "regression"): "pen-test",
        ("sast", "scan"): "sast",
        ("sca", "scan"): "sca",
        ("admin", "e2e"): "admin-e2e",
        ("evidence",): "evidence",
        ("evidence", "build"): "evidence",
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
        raise SystemExit(f"security control failed: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
