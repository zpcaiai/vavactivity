from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]


def test_admin_platform_never_directly_updates_authoritative_domain_facts() -> None:
    source = (
        (ROOT / "services/api/src/vav/modules/admin_platform/service.py").read_text().casefold()
    )
    forbidden = [
        "update payments",
        "update orders",
        "update consents",
        "update relationship_journeys",
        "update safety_restrictions",
        "update membership_accounts",
    ]
    assert not any(statement in source for statement in forbidden)


def test_admin_platform_has_no_arbitrary_sql_or_sensitive_response_fields() -> None:
    router = (
        (ROOT / "services/api/src/vav/modules/admin_platform/admin_router.py")
        .read_text()
        .casefold()
    )
    assert "sql_console" not in router and "arbitrary_sql" not in router
    assert "reason_encrypted" not in router and "request_payload_encrypted" not in router
