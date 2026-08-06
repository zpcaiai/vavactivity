from __future__ import annotations

from pathlib import Path

from vav.modules.process_governance.domain import FORBIDDEN_REPAIR_MARKERS

ROOT = Path(__file__).resolve().parents[5]


def test_process_module_has_no_domain_table_mutation_sql() -> None:
    service = (
        (ROOT / "services/api/src/vav/modules/process_governance/service.py")
        .read_text(encoding="utf-8")
        .casefold()
    )
    forbidden_tables = [
        "orders set",
        "payments set",
        "activity_registrations set",
        "relationship_journeys set",
        "privacy_requests set",
    ]
    assert not any(f"update {table}" in service for table in forbidden_tables)


def test_database_and_policy_reject_unsafe_operator_repairs() -> None:
    migration = (
        (ROOT / "services/api/migrations/versions/20260806_0090_process_governance.py")
        .read_text(encoding="utf-8")
        .casefold()
    )
    assert all(marker in migration for marker in {"direct_sql", "set_state", "fabricate"})
    assert {"direct_sql", "set_state", "fabricate"}.issubset(FORBIDDEN_REPAIR_MARKERS)
