"""Batch 29-32 external execution evidence must fail closed."""

from __future__ import annotations

import json

from scripts.final import control as final_control
from scripts.performance import control as performance_control
from scripts.resilience import control as resilience_control
from scripts.security import control as security_control


def test_batch_29_performance_execution_is_not_inferred_from_fixtures(
    monkeypatch,
) -> None:
    monkeypatch.delenv("PERFORMANCE_EVIDENCE_DIR", raising=False)
    monkeypatch.setattr(performance_control, "_git_commit", lambda: "a" * 40)

    snapshot = performance_control.snapshot()

    assert snapshot["external_evidence_pending"] == 5
    for name in ("baseline", "load", "spike", "stress", "soak"):
        assert snapshot[name]["simulation_status"].lower() in {
            "pass",
            "passed",
            "passed_with_warnings",
        }
        assert snapshot[name]["status"] == "NOT_EVALUATED"


def test_batch_30_security_execution_is_not_inferred_from_policy(
    monkeypatch,
) -> None:
    monkeypatch.delenv("SECURITY_EVIDENCE_DIR", raising=False)
    monkeypatch.setattr(security_control, "_git_commit", lambda: "a" * 40)

    snapshot = security_control.snapshot()

    for name in (
        "sast",
        "sca",
        "secret_scan",
        "iac_scan",
        "container_scan",
        "api_dast",
        "api_fuzz",
        "penetration",
    ):
        assert snapshot[name]["status"] == "NOT_EVALUATED"
    assert security_control._technical_report()["technical_status"] == "NOT_EVALUATED"


def test_batch_31_resilience_execution_is_not_inferred_from_scenarios(
    monkeypatch,
) -> None:
    monkeypatch.delenv("RESILIENCE_EVIDENCE_DIR", raising=False)
    monkeypatch.setattr(resilience_control, "_git_commit", lambda: "a" * 40)

    snapshot = resilience_control._snapshot()

    assert snapshot["technical_status"] == "NOT_EVALUATED"
    for name in (
        "api_ha_tests",
        "database_ha_tests",
        "redis_worker_ha_tests",
        "chaos_tests",
        "backup_restore_tests",
        "disaster_recovery_tests",
    ):
        assert snapshot[name]["status"] == "NOT_EVALUATED"


def test_batch_32_release_stays_blocked_without_current_external_evidence(
    monkeypatch,
) -> None:
    monkeypatch.delenv("FINAL_EVIDENCE_DIR", raising=False)
    monkeypatch.setattr(final_control, "_git_commit", lambda: "a" * 40)

    snapshot = final_control._snapshot()

    assert snapshot["score"]["status"] == "NOT_EVALUATED"
    assert snapshot["go_no_go"]["status"] == "NOT_EVALUATED"
    assert snapshot["approval"]["status"] == "NOT_EVALUATED"
    assert all(
        observation["status"] == "NOT_EVALUATED"
        for observation in snapshot["observation"].values()
    )
    assert snapshot["technical_status"] != "PASS"


def test_external_evidence_from_another_commit_is_rejected(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("SECURITY_EVIDENCE_DIR", str(tmp_path))
    monkeypatch.setattr(security_control, "_git_commit", lambda: "a" * 40)
    (tmp_path / "sast.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "git_commit": "b" * 40,
                "artifact_sha256": "c" * 64,
                "completed_at": "2026-08-09T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    evidence = security_control._external_evidence("sast")

    assert evidence == {
        "status": "FAIL",
        "reason": "external evidence commit mismatch",
    }


def test_final_approval_evidence_requires_role_identity_and_decision(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("FINAL_EVIDENCE_DIR", str(tmp_path))
    monkeypatch.setattr(final_control, "_git_commit", lambda: "a" * 40)
    (tmp_path / "approval-production-owner.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "git_commit": "a" * 40,
                "artifact_sha256": "c" * 64,
                "completed_at": "2026-08-09T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    result = final_control._approval_checks(
        {"approvals": {"production_owner": {"required": True}}}
    )

    assert result["status"] == "FAIL"
    assert result["findings"] == [
        "production_owner:approval_decision_missing",
        "production_owner:approval_role_mismatch",
        "production_owner:approver_identity_missing",
        "production_owner:approval_time_missing",
    ]
