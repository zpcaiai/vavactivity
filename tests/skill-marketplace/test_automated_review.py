from __future__ import annotations

from typing import Any

from vav.modules.skills_platform.marketplace_review import (
    AutomatedReviewReport,
    automated_review,
)


def _review(**overrides: Any) -> AutomatedReviewReport:
    values = {
        "manifest": {
            "spec": {
                "permissions": [],
                "data": {"reads": [], "writes": []},
                "security": {"networkAccess": "none"},
            }
        },
        "signature_verified": True,
        "security_passed": True,
        "compatible": True,
        "sbom_present": True,
        "provenance_present": True,
        "privacy_disclosure": {
            "reads": [],
            "writes": [],
            "externalDestinations": [],
            "retention": "none",
            "deletion": "on uninstall",
            "modelTraining": False,
            "automatedDecision": False,
        },
        "support_policy": {
            "contact": "support@example.com",
            "endOfSupportPolicy": "90 day notice",
        },
    }
    values.update(overrides)
    return automated_review(**values)  # type: ignore[arg-type]


def test_signed_disclosed_package_enters_human_review() -> None:
    report = _review()
    assert report.passed is True
    assert report.requires_human_review is True


def test_unsigned_or_missing_supply_chain_evidence_is_blocked() -> None:
    report = _review(
        signature_verified=False, sbom_present=False, provenance_present=False
    )
    assert report.passed is False
    assert set(report.blockers) >= {"signature", "sbom", "provenance"}


def test_private_ssrf_and_undisclosed_access_are_blocked() -> None:
    report = _review(
        manifest={
            "spec": {
                "permissions": ["knowledge.search.internal"],
                "data": {"reads": ["profiles.private"], "writes": []},
                "security": {"networkAccess": "allowlist"},
            }
        },
        privacy_disclosure={
            "reads": [],
            "writes": [],
            "externalDestinations": ["https://127.0.0.1/metadata"],
            "retention": "none",
            "deletion": "on uninstall",
            "modelTraining": False,
            "automatedDecision": False,
        },
    )
    assert report.passed is False
    assert "unsafe_external_destination" in report.blockers
    assert "undisclosed_reads" in report.blockers


def test_prohibited_permission_is_rejected() -> None:
    report = _review(
        manifest={
            "spec": {
                "permissions": ["identity.credentials.read"],
                "data": {"reads": [], "writes": []},
                "security": {"networkAccess": "none"},
            }
        }
    )
    assert report.passed is False
    assert "prohibited_permission" in report.blockers
