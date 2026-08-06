from __future__ import annotations

import pytest

from vav.common.exceptions import VavError
from vav.modules.experience.domain import (
    closure_checks,
    evaluate_route,
    minimize_feedback_context,
    scan_route_graph,
    validate_identifier_context,
)


def test_handoff_context_accepts_only_declared_non_sensitive_identifiers() -> None:
    validate_identifier_context({"match_id": "8bc0ac87-81fa-43b2-89f9-75652aaf20b9"}, {"match_id"})
    with pytest.raises(VavError, match="Sensitive"):
        validate_identifier_context({"phone": "13800000000"}, {"phone"})
    with pytest.raises(VavError, match="outside"):
        validate_identifier_context({"unexpected_id": "value"}, {"match_id"})


def test_restrictions_keep_safe_rights_reachable() -> None:
    safety = {
        "route_code": "user.safety",
        "permission_codes": [],
        "capability_codes": [],
        "prerequisite_policy": {"denied_restrictions": ["account_limited"]},
    }
    dating = {**safety, "route_code": "user.recommendations", "fallback_route_code": "user.safety"}
    assert evaluate_route(
        safety,
        authenticated=True,
        permissions=set(),
        capabilities=set(),
        enabled_features=set(),
        restriction_codes={"account_limited"},
    ).eligible
    decision = evaluate_route(
        dating,
        authenticated=True,
        permissions=set(),
        capabilities=set(),
        enabled_features=set(),
        restriction_codes={"account_limited"},
    )
    assert not decision.eligible
    assert decision.fallback_route_code == "user.safety"


def test_route_graph_finds_broken_critical_links_and_closure_fails_closed() -> None:
    routes = [
        {
            "route_code": "user.home",
            "route_type": "page",
            "critical": True,
            "authentication_required": False,
            "ia_node_code": "public.home",
            "page_code": "home",
            "permission_codes": [],
            "help_context_code": "help.home",
            "fallback_route_code": "missing",
        }
    ]
    assert {item["type"] for item in scan_route_graph(routes)} >= {"broken_link"}
    checks = closure_checks(routes[0])
    assert all(checks.values())


def test_feedback_context_drops_sensitive_fields() -> None:
    assert minimize_feedback_context(
        {"route_state": "blocked", "email": "private@example.com", "count": 2}
    ) == {"route_state": "blocked", "count": 2}
