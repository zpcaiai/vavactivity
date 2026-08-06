from __future__ import annotations

from pathlib import Path

from vav.modules.data_governance.domain import IDENTITY_FORBIDDEN, minimize_evidence

ROOT = Path(__file__).resolve().parents[5]


def test_data_governance_has_no_direct_authoritative_fact_updates() -> None:
    source = (
        (ROOT / "services/api/src/vav/modules/data_governance/service.py")
        .read_text(encoding="utf-8")
        .casefold()
    )
    forbidden = [
        "update payments",
        "update orders",
        "update consents",
        "update relationship_journeys",
        "update membership_accounts",
        "update safety_restrictions",
    ]
    assert not any(statement in source for statement in forbidden)


def test_canonical_identity_and_minimized_evidence_reject_direct_identifiers() -> None:
    assert {"email", "phone", "display_name", "provider_id"}.issubset(IDENTITY_FORBIDDEN)
    assert minimize_evidence({"phone": "+886900000000", "entity_id": "safe", "rows": 1}) == {
        "entity_id": "safe",
        "rows": 1,
    }


def test_migration_forbids_unsafe_repair_command_markers() -> None:
    migration = (
        (ROOT / "services/api/migrations/versions/20260806_0091_data_integrity_governance.py")
        .read_text(encoding="utf-8")
        .casefold()
    )
    assert all(
        marker in migration for marker in ("direct_sql", "set_state", "mark_paid", "fabricate")
    )
