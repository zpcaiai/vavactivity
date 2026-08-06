from vav.main import create_app
from vav.modules.trust_safety.domain import REGISTERED_SIGNALS, TrustSafetyDecision


def test_decision_contract_never_exposes_reports_evidence_or_rules() -> None:
    decision = TrustSafetyDecision(
        allowed=False,
        action="deny",
        safe_reason_code="pair_blocked",
        restriction_version=3,
        decision_id=__import__("uuid").uuid4(),
    ).as_dict()
    assert set(decision) == {
        "allowed",
        "action",
        "safe_reason_code",
        "restriction_version",
        "decision_id",
        "expires_at",
        "human_review_required",
    }
    assert not ({"reporter_user_id", "evidence", "rule_definition"} & set(decision))


def test_sensitive_admin_and_user_routes_are_separate() -> None:
    paths = create_app().openapi()["paths"]
    assert "/api/v1/account/safety/reports/{report_id}" in paths
    assert "/api/v1/admin/trust-safety/reports" in paths
    assert "get" not in paths.get("/api/v1/safety/reports", {})


def test_protected_attributes_are_not_registered_risk_signals() -> None:
    assert not ({"religion", "nationality", "race", "counseling_content"} & REGISTERED_SIGNALS)
