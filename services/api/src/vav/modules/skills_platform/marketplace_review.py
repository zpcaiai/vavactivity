"""Deterministic Marketplace automated-review policy."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

PROHIBITED_PERMISSION_MARKERS = (
    "credentials",
    "account.takeover",
    "profiles.private.bulk",
    "blocks.bypass",
    "payment.bypass",
    "code.execute.arbitrary",
    "reporter.identity",
)
HIGH_RISK_MARKERS = (".sensitive.", ".export", ".payment", ".send", ".restrict", "secrets.")


@dataclass(frozen=True)
class AutomatedReviewReport:
    passed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    requires_human_review: bool
    gates: dict[str, bool]

    def canonical(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "requires_human_review": self.requires_human_review,
            "gates": self.gates,
        }


def _safe_external_destination(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 500:
        return False
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return False
    hostname = parsed.hostname.rstrip(".").casefold()
    if hostname in {"localhost", "metadata.google.internal"} or hostname.endswith(".local"):
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return "*" not in hostname and "." in hostname
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
    )


def automated_review(
    *,
    manifest: dict[str, Any],
    signature_verified: bool,
    security_passed: bool,
    compatible: bool,
    sbom_present: bool,
    provenance_present: bool,
    privacy_disclosure: dict[str, Any],
    support_policy: dict[str, Any],
) -> AutomatedReviewReport:
    spec = manifest.get("spec", {})
    permissions = spec.get("permissions", [])
    declared_data = spec.get("data", {})
    destinations = privacy_disclosure.get("externalDestinations", [])
    gates = {
        "signature": signature_verified,
        "security": security_passed,
        "compatibility": compatible,
        "sbom": sbom_present,
        "provenance": provenance_present,
        "data_disclosure": all(
            key in privacy_disclosure
            for key in (
                "reads",
                "writes",
                "externalDestinations",
                "retention",
                "deletion",
                "modelTraining",
                "automatedDecision",
            )
        ),
        "support_policy": bool(support_policy.get("contact"))
        and bool(support_policy.get("endOfSupportPolicy")),
    }
    blockers = [name for name, passed in gates.items() if not passed]
    if any(
        marker in str(permission)
        for permission in permissions
        for marker in PROHIBITED_PERMISSION_MARKERS
    ):
        blockers.append("prohibited_permission")
    if set(declared_data.get("reads", [])) - set(privacy_disclosure.get("reads", [])):
        blockers.append("undisclosed_reads")
    if set(declared_data.get("writes", [])) - set(privacy_disclosure.get("writes", [])):
        blockers.append("undisclosed_writes")
    if not isinstance(destinations, list) or not all(
        _safe_external_destination(item) for item in destinations
    ):
        blockers.append("unsafe_external_destination")
    if spec.get("security", {}).get("networkAccess") == "allowlist" and not destinations:
        blockers.append("network_destination_not_disclosed")
    warnings: list[str] = []
    if any(marker in str(permission) for permission in permissions for marker in HIGH_RISK_MARKERS):
        warnings.append("high_risk_permission")
    if privacy_disclosure.get("modelTraining"):
        warnings.append("model_training_disclosed")
    unique_blockers = tuple(sorted(set(blockers)))
    return AutomatedReviewReport(
        passed=not unique_blockers,
        blockers=unique_blockers,
        warnings=tuple(sorted(set(warnings))),
        requires_human_review=True,
        gates=gates,
    )
