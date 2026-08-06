"""Evidence binding, expiry, tampering and cross-release reuse."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from vav.modules.quality.domain import (
    EvidenceRecord,
    QualityEvidenceStatus,
    QualityEvidenceType,
    content_fingerprint,
    evidence_rejection_reasons,
    select_gate_evidence,
)

NOW = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
RELEASE = "2026.08.0-rc.1"
COMMIT = "a" * 40
ENVIRONMENT = "staging"
ACCEPTED = frozenset({QualityEvidenceType.E2E_REPORT})
SUMMARY = {"critical_journey_e2e_pass_rate": 1.0}
CHECKSUM = content_fingerprint(SUMMARY)


def _evidence(**overrides: object) -> EvidenceRecord:
    payload: dict[str, object] = {
        "code": "EVID-E2E-001",
        "evidence_type": QualityEvidenceType.E2E_REPORT,
        "status": QualityEvidenceStatus.ACCEPTED,
        "release_version": RELEASE,
        "git_commit": COMMIT,
        "environment": ENVIRONMENT,
        "checksum_sha256": CHECKSUM,
        "generated_at": NOW - timedelta(hours=1),
        "expires_at": NOW + timedelta(days=7),
        "summary": SUMMARY,
    }
    payload.update(overrides)
    return EvidenceRecord(**payload)  # type: ignore[arg-type]


def _reasons(record: EvidenceRecord, **overrides: object) -> tuple[str, ...]:
    payload: dict[str, object] = {
        "release_version": RELEASE,
        "git_commit": COMMIT,
        "environment": ENVIRONMENT,
        "accepted_types": ACCEPTED,
        "now": NOW,
    }
    payload.update(overrides)
    return evidence_rejection_reasons(record, **payload)  # type: ignore[arg-type]


def test_valid_evidence_has_no_rejection_reason() -> None:
    assert _reasons(_evidence()) == ()


def test_unaccepted_evidence_is_rejected() -> None:
    assert "evidence_not_accepted" in _reasons(
        _evidence(status=QualityEvidenceStatus.GENERATED)
    )


def test_expired_evidence_cannot_certify_a_release() -> None:
    assert "evidence_expired" in _reasons(_evidence(expires_at=NOW - timedelta(seconds=1)))


def test_evidence_from_another_release_is_rejected() -> None:
    assert "evidence_release_mismatch" in _reasons(_evidence(release_version="2026.07.0"))


def test_evidence_from_another_commit_is_rejected() -> None:
    assert "evidence_commit_mismatch" in _reasons(_evidence(git_commit="b" * 40))


def test_evidence_from_another_environment_is_rejected() -> None:
    assert "evidence_environment_mismatch" in _reasons(_evidence(environment="production"))


def test_wrong_evidence_type_for_the_gate_is_rejected() -> None:
    assert "evidence_type_not_accepted_by_gate" in _reasons(
        _evidence(evidence_type=QualityEvidenceType.SCREENSHOT)
    )


def test_tampered_evidence_is_rejected() -> None:
    reasons = _reasons(_evidence(), recomputed_checksum=content_fingerprint({"changed": True}))
    assert "evidence_checksum_mismatch" in reasons


def test_missing_checksum_is_rejected() -> None:
    assert "evidence_checksum_missing" in _reasons(_evidence(checksum_sha256=""))


def test_test_name_without_result_is_not_evidence() -> None:
    assert "evidence_summary_empty" in _reasons(_evidence(summary={}))


def test_gate_selection_fails_closed_when_nothing_is_usable() -> None:
    observed, reasons = select_gate_evidence(
        [_evidence(status=QualityEvidenceStatus.REJECTED)],
        metric="critical_journey_e2e_pass_rate",
        release_version=RELEASE,
        git_commit=COMMIT,
        environment=ENVIRONMENT,
        accepted_types=ACCEPTED,
        now=NOW,
    )
    assert observed is None
    assert "evidence_not_accepted" in reasons


def test_gate_selection_fails_closed_with_no_evidence_at_all() -> None:
    observed, reasons = select_gate_evidence(
        [],
        metric="critical_journey_e2e_pass_rate",
        release_version=RELEASE,
        git_commit=COMMIT,
        environment=ENVIRONMENT,
        accepted_types=ACCEPTED,
        now=NOW,
    )
    assert observed is None
    assert reasons == ("required_current_evidence_missing",)


def test_gate_selection_prefers_the_newest_usable_evidence() -> None:
    stale = _evidence(
        code="EVID-E2E-OLD",
        generated_at=NOW - timedelta(days=2),
        summary={"critical_journey_e2e_pass_rate": 0.5},
        checksum_sha256=content_fingerprint({"critical_journey_e2e_pass_rate": 0.5}),
    )
    observed, reasons = select_gate_evidence(
        [stale, _evidence()],
        metric="critical_journey_e2e_pass_rate",
        release_version=RELEASE,
        git_commit=COMMIT,
        environment=ENVIRONMENT,
        accepted_types=ACCEPTED,
        now=NOW,
    )
    assert observed == 1.0
    assert reasons == ()


def test_usable_evidence_without_the_metric_reports_the_reason() -> None:
    observed, reasons = select_gate_evidence(
        [_evidence(summary={"other_metric": 1.0}, checksum_sha256=CHECKSUM)],
        metric="critical_journey_e2e_pass_rate",
        release_version=RELEASE,
        git_commit=COMMIT,
        environment=ENVIRONMENT,
        accepted_types=ACCEPTED,
        now=NOW,
    )
    assert observed is None
    assert reasons == ("gate_metric_absent_from_evidence",)
