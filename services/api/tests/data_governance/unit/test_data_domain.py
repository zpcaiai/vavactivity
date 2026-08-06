from __future__ import annotations

from vav.modules.data_governance.domain import (
    contract_diff,
    erasure_action,
    event_disposition,
    minimize_evidence,
    validate_asset,
    validate_lineage,
    validate_rule,
)


def test_asset_ownership_and_canonical_identity_are_enforced() -> None:
    valid = {
        "truth": True,
        "projection": False,
        "rebuildable": False,
        "module": "commerce",
        "classification": "restricted",
        "retention": "financial",
        "erasure": "anonymize",
        "identifier": "payment_id",
    }
    assert validate_asset(valid) == []
    invalid = {
        **valid,
        "truth": False,
        "projection": True,
        "rebuildable": False,
        "identifier": "email",
    }
    assert set(validate_asset(invalid)) == {"projection_not_rebuildable", "noncanonical_identifier"}


def test_contract_diff_flags_required_and_sensitive_breaks() -> None:
    old = {"required": ["id", "version"], "sensitive": ["secret"]}
    new = {"required": ["id", "new_required"], "sensitive": []}
    result = contract_diff(old, new)
    assert result["compatibility_status"] == "breaking"
    assert set(result["breaking_reasons"]) == {
        "required_fields_removed",
        "new_required_fields",
        "sensitive_fields_declassified",
    }


def test_lineage_rejects_orphan_projection_and_unsafe_sensitive_flow() -> None:
    assets = [
        {
            "code": "source",
            "truth": True,
            "projection": False,
            "classification": "highly_restricted",
        },
        {"code": "projection", "truth": False, "projection": True, "classification": "public"},
    ]
    findings = validate_lineage(
        assets,
        [{"source": "source", "target": "projection", "transform": "copy", "erasure": False}],
    )
    assert {item["code"] for item in findings} == {
        "undeclared_sensitive_flow",
        "missing_erasure_propagation",
    }


def test_event_ordering_never_advances_across_gap() -> None:
    assert event_disposition(2, 2) == "rejected_old"
    assert event_disposition(2, 3) == "accepted"
    assert event_disposition(2, 5) == "buffered_future"


def test_quality_rules_are_declarative_only() -> None:
    assert validate_rule({"operator": "not_null", "threshold": 0}) == []
    assert set(
        validate_rule({"operator": "custom", "expression": "DELETE FROM users;", "threshold": -1})
    ) == {"unsupported_operator", "imperative_sql_forbidden", "negative_threshold"}


def test_erasure_actions_cover_cache_search_vector_export_and_source() -> None:
    assert (
        erasure_action({"type": "cache", "projection": True, "erasure": "cache-invalidate"})
        == "invalidate_cache"
    )
    assert (
        erasure_action({"type": "search_index", "projection": True, "erasure": "search-remove"})
        == "remove_search"
    )
    assert (
        erasure_action({"type": "vector_index", "projection": True, "erasure": "vector-remove"})
        == "remove_vector"
    )
    assert (
        erasure_action({"type": "file_export", "projection": True, "erasure": "export-remove"})
        == "remove_export"
    )
    assert (
        erasure_action(
            {"type": "database_table", "projection": False, "erasure": "financial-anonymize"}
        )
        == "anonymize"
    )


def test_failure_evidence_is_minimized() -> None:
    assert minimize_evidence({"email": "person@example.com", "entity_id": "abc", "count": 2}) == {
        "entity_id": "abc",
        "count": 2,
    }
