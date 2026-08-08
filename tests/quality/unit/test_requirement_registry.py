"""Requirement and capability lifecycle, codes and idempotent versioned upsert."""

from __future__ import annotations

import pytest

from vav.modules.quality.domain import (
    CAPABILITY_CODE_PATTERN,
    CAPABILITY_TRANSITIONS,
    DEFINITION_OF_DONE,
    DEFINITION_OF_READY,
    GATE_CODE_PATTERN,
    REQUIREMENT_CODE_PATTERN,
    REQUIREMENT_TRANSITIONS,
    QualityCriticality,
    QualityPolicyError,
    QualityRequirementStatus,
    content_fingerprint,
    criticality_rank,
    next_semantic_version,
    plan_versioned_upsert,
    validate_capability_transition,
    validate_code,
    validate_requirement_transition,
)


@pytest.mark.parametrize(
    "code",
    [
        "REQ-VAV-AUTH-001",
        "REQ-VAV-COMMERCE-014",
        "REQ-VAV-PRIVACY-009",
        "REQ-VAV-SAFETY-021",
        "REQ-VAV-QUALITY-001",
    ],
)
def test_published_requirement_codes_are_accepted(code: str) -> None:
    assert validate_code(code, REQUIREMENT_CODE_PATTERN, "Requirement") == code


@pytest.mark.parametrize(
    "code",
    ["req-vav-auth-001", "REQ-AUTH-001", "REQ-VAV-AUTH-1", "REQ VAV AUTH 001", ""],
)
def test_malformed_requirement_codes_are_rejected(code: str) -> None:
    with pytest.raises(QualityPolicyError) as error:
        validate_code(code, REQUIREMENT_CODE_PATTERN, "Requirement")
    assert error.value.code == "QUALITY_CODE_INVALID"


@pytest.mark.parametrize(
    "code",
    [
        "CAP-AUTH-REGISTER",
        "CAP-COMMERCE-CHECKOUT",
        "CAP-SAFETY-BLOCK-PROPAGATE",
        "CAP-PRIVACY-ERASURE",
        "CAP-SKILL-INSTALL",
    ],
)
def test_published_capability_codes_are_accepted(code: str) -> None:
    assert validate_code(code, CAPABILITY_CODE_PATTERN, "Capability") == code


def test_gate_code_pattern_accepts_published_gates() -> None:
    for code in (
        "GATE-REQ-BLOCKER-COVERAGE",
        "GATE-FLOW-CRITICAL-CLOSURE",
        "GATE-SECURITY-CRITICAL",
        "GATE-RESTORE-DRILL",
    ):
        assert validate_code(code, GATE_CODE_PATTERN, "Gate") == code


def test_implemented_and_verified_are_separate_states() -> None:
    assert QualityRequirementStatus.IMPLEMENTED != QualityRequirementStatus.VERIFIED
    validate_requirement_transition("implemented", "verified")
    with pytest.raises(QualityPolicyError):
        validate_requirement_transition("in_implementation", "verified")


def test_verified_requirement_can_only_be_superseded() -> None:
    assert REQUIREMENT_TRANSITIONS["verified"] == frozenset({"superseded"})
    with pytest.raises(QualityPolicyError) as error:
        validate_requirement_transition("verified", "draft")
    assert error.value.code == "QUALITY_REQUIREMENT_TRANSITION_INVALID"


def test_superseded_and_rejected_are_terminal() -> None:
    assert REQUIREMENT_TRANSITIONS["superseded"] == frozenset()
    assert REQUIREMENT_TRANSITIONS["rejected"] == frozenset()


def test_unknown_requirement_state_is_rejected() -> None:
    with pytest.raises(QualityPolicyError) as error:
        validate_requirement_transition("almost_done", "verified")
    assert error.value.code == "QUALITY_REQUIREMENT_STATE_UNKNOWN"


def test_capability_lifecycle_terminals() -> None:
    validate_capability_transition("planned", "in_development")
    validate_capability_transition("available", "deprecated")
    assert CAPABILITY_TRANSITIONS["retired"] == frozenset()
    with pytest.raises(QualityPolicyError) as error:
        validate_capability_transition("retired", "available")
    assert error.value.code == "QUALITY_CAPABILITY_TRANSITION_INVALID"


def test_criticality_ordering() -> None:
    assert criticality_rank(QualityCriticality.BLOCKER) > criticality_rank(
        QualityCriticality.CRITICAL
    )
    assert criticality_rank("minor") == 0


def test_definition_of_ready_and_done_are_complete() -> None:
    assert len(DEFINITION_OF_READY) == 10
    assert len(DEFINITION_OF_DONE) == 13
    assert "acceptance_evidence" in DEFINITION_OF_DONE
    assert "privacy_classification" in DEFINITION_OF_READY


def test_reimporting_an_identical_manifest_is_idempotent() -> None:
    payload = {"title": "Payment confirms before entitlement", "criticality": "blocker"}
    first = plan_versioned_upsert(code="REQ-VAV-COMMERCE-001", payload=payload)
    assert first.changed is True
    assert first.version == "1.0.0"

    second = plan_versioned_upsert(
        code="REQ-VAV-COMMERCE-001",
        payload=payload,
        existing_version=first.version,
        existing_fingerprint=first.fingerprint,
    )
    assert second.changed is False
    assert second.version == "1.0.0"


def test_content_change_creates_a_new_version_and_keeps_history() -> None:
    payload = {"title": "Payment confirms before entitlement"}
    first = plan_versioned_upsert(code="REQ-VAV-COMMERCE-001", payload=payload)
    changed = plan_versioned_upsert(
        code="REQ-VAV-COMMERCE-001",
        payload={"title": "Webhook confirms before entitlement"},
        existing_version=first.version,
        existing_fingerprint=first.fingerprint,
    )
    assert changed.changed is True
    assert changed.version == "1.1.0"
    assert changed.previous_version == "1.0.0"


def test_breaking_change_bumps_major() -> None:
    result = plan_versioned_upsert(
        code="CAP-COMMERCE-CHECKOUT",
        payload={"contract": "v2"},
        existing_version="1.4.0",
        existing_fingerprint="stale",
        breaking=True,
    )
    assert result.version == "2.0.0"


def test_fingerprint_is_order_independent() -> None:
    assert content_fingerprint({"a": 1, "b": 2}) == content_fingerprint(
        {"b": 2, "a": 1}
    )


def test_invalid_semantic_version_is_rejected() -> None:
    with pytest.raises(QualityPolicyError) as error:
        next_semantic_version("1.0")
    assert error.value.code == "QUALITY_VERSION_INVALID"
