from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/certification/external_gate_intake.py"
SPEC = importlib.util.spec_from_file_location("external_gate_intake", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
intake = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = intake
SPEC.loader.exec_module(intake)


def template() -> dict:
    value = yaml.safe_load(
        (ROOT / "config/certification/external-gate-intake.template.yaml").read_text()
    )
    assert isinstance(value, dict)
    return value


def test_json_schema_is_versioned_and_accepts_the_template_shape() -> None:
    schema = json.loads(
        (ROOT / "config/certification/external-gate-intake.schema.json").read_text()
    )
    config = template()

    assert schema["$schema"].endswith("2020-12/schema")
    assert schema["properties"]["schema_version"]["const"] == config["schema_version"]
    assert set(schema["required"]).issubset(config)


def evidence(path: Path, content: bytes = b"approved") -> dict[str, str]:
    path.write_bytes(content)
    return {"path": str(path), "sha256": hashlib.sha256(content).hexdigest()}


def test_current_production_target_is_complete_and_stably_fingerprinted() -> None:
    config = template()

    first, first_result = intake.validate_target(config)
    second, second_result = intake.validate_target(config)

    assert first_result["status"] == "PASS"
    assert second_result["status"] == "PASS"
    assert first["selection"] == "current_production"
    assert first["target_fingerprint"] == second["target_fingerprint"]
    assert len(first["target_fingerprint"]) == 64
    assert first["artifacts"]["backend"]["digest"] == "not_applicable"


def test_latest_feature_cannot_be_selected_without_backend_deployment() -> None:
    config = template()
    config["certification_target"] = "latest_feature"

    _, result = intake.validate_target(config)

    assert result["status"] == "BLOCKED"
    assert "target.backend_deployment_id.missing" in result["findings"]


def test_accounts_use_environment_references_and_never_embed_secrets(
    monkeypatch,
) -> None:
    config = template()
    for item in config["test_accounts"]["accounts"]:
        monkeypatch.setenv(item["username_env"], "synthetic@example.invalid")
        monkeypatch.setenv(item["password_env"], "not-returned-by-report")
        item["expires_at"] = "2026-08-14T00:00:00Z"

    result = intake.validate_accounts(
        config, now=datetime(2026, 8, 13, 5, tzinfo=UTC)
    )

    assert result["status"] == "PASS"
    serialized = json.dumps(result)
    assert "not-returned-by-report" not in serialized
    assert "synthetic@example.invalid" not in serialized


def test_device_gate_accepts_physical_devices_or_an_authenticated_cloud(
    monkeypatch,
) -> None:
    config = template()
    config["device_uat"]["device_cloud"] = {
        "provider": "approved-device-cloud",
        "credential_env": "VAV_DEVICE_CLOUD_TOKEN",
    }
    monkeypatch.setenv("VAV_DEVICE_CLOUD_TOKEN", "secret-not-reported")

    result = intake.validate_devices(
        config,
        {
            "ios_physical_online": [],
            "ios_physical_offline": ["Ethan (27.0)"],
            "android_physical_online": [],
        },
    )

    assert result["status"] == "PASS"
    assert "secret-not-reported" not in json.dumps(result)


def test_written_security_authorization_is_bound_to_scope_window_and_checksum(
    tmp_path: Path,
) -> None:
    config = template()
    target, _ = intake.validate_target(config)
    authorization = config["security_authorization"]
    authorization.update(
        {
            "approved": True,
            "authorization_id": "SEC-2026-001",
            "authorizing_owner": "Production Owner",
            "owner_organization": "VAV",
            "starts_at": "2026-08-13T00:00:00Z",
            "ends_at": "2026-08-14T00:00:00Z",
            "source_ip_cidrs": ["203.0.113.7/32"],
            "independent_test_provider": {
                "organization": "Independent Security Lab",
                "lead_tester": "Security Tester",
            },
            "emergency_stop_contact": {
                "name": "Incident Commander",
                "contact": "approved-channel-reference",
            },
            "written_authorization_evidence": evidence(tmp_path / "authorization.pdf"),
        }
    )

    result = intake.validate_security_authorization(
        config,
        base=tmp_path,
        target=target,
        now=datetime(2026, 8, 13, 5, tzinfo=UTC),
    )

    assert result["status"] == "PASS"


def test_owner_approvals_must_match_the_exact_target_fingerprint(tmp_path: Path) -> None:
    config = template()
    target, _ = intake.validate_target(config)
    for role, item in config["owner_approvals"].items():
        item.update(
            {
                "approved": True,
                "approver": f"Named {role}",
                "approved_at": "2026-08-13T05:00:00Z",
                "target_fingerprint": target["target_fingerprint"],
                "evidence": evidence(tmp_path / f"{role}.pdf", role.encode()),
            }
        )

    passed = intake.validate_approvals(
        config,
        base=tmp_path,
        target_fingerprint=target["target_fingerprint"],
    )
    config["owner_approvals"]["security_owner"]["target_fingerprint"] = "0" * 64
    blocked = intake.validate_approvals(
        config,
        base=tmp_path,
        target_fingerprint=target["target_fingerprint"],
    )

    assert passed["status"] == "PASS"
    assert blocked["status"] == "BLOCKED"
    assert (
        "owner_approvals.security_owner.target_fingerprint_mismatch"
        in blocked["findings"]
    )


def test_template_remains_fail_closed_without_external_inputs(monkeypatch) -> None:
    config = template()
    monkeypatch.setattr(
        intake,
        "_probe_url",
        lambda _url: {"status_code": 200, "ok": True},
    )
    monkeypatch.setattr(
        intake,
        "probe_devices",
        lambda: {
            "ios_physical_online": [],
            "ios_physical_offline": ["Ethan"],
            "android_physical_online": [],
        },
    )

    report = intake.preflight(
        config,
        source=ROOT / "config/certification/external-gate-intake.template.yaml",
        now=datetime(2026, 8, 13, 5, tzinfo=UTC),
    )

    assert report["status"] == "BLOCKED"
    assert report["production_certification"] is False
    assert report["release_allowed"] is False
    assert "certification_target" not in report["blocked_sections"]
    assert "security_authorization" in report["blocked_sections"]
    assert "owner_approvals" in report["blocked_sections"]
