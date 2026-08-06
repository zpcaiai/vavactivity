"""There is no administrator path to a member's choice."""

# ruff: noqa: E501
from __future__ import annotations

import inspect

import pytest

from vav.main import app
from vav.modules.identity.permissions import (
    MATCHMAKING_INTERACTION_PERMISSIONS,
    ROLE_PERMISSIONS,
)
from vav.modules.matchmaking_interactions import admin_router
from vav.modules.matchmaking_interactions.schemas import (
    AdminInvalidateRequest,
    AdminSensitiveReadRequest,
)

ADMIN_PREFIX = "/api/v1/admin/matchmaking/interactions"


def _admin_paths() -> list[str]:
    return [
        route.path
        for route in app.routes
        if hasattr(route, "path") and route.path.startswith(ADMIN_PREFIX)
    ]


def test_no_admin_route_creates_a_choice() -> None:
    """Liking, accepting, declining and consenting have no admin equivalent.

    This is checked against the live route table rather than by review, so a
    future endpoint that crosses the line fails the build.
    """
    forbidden = ("/like", "/accept", "/decline", "/consent", "/match/create", "/skip")
    for path in _admin_paths():
        for fragment in forbidden:
            assert fragment not in path, f"{path} would let an administrator act for a member"


def test_the_admin_surface_is_diagnose_and_repair_only() -> None:
    allowed_suffixes = (
        "/dashboard",
        "/matches",
        "/invitations",
        "/audit",
        "/dead-letters",
        "/diagnostics/duplicates",
        "/pairs/{pair_id}",
        "/pairs/{pair_id}/sensitive",
        "/pairs/{pair_id}/invalidate",
        "/invitations/{invitation_id}/content",
        "/contact-exchanges/{exchange_id}/revoke",
        "/dead-letters/{dead_letter_id}/resolve",
    )
    for path in _admin_paths():
        tail = path[len(ADMIN_PREFIX) :]
        assert tail in allowed_suffixes, f"unexpected administrator route {path}"


def test_there_is_no_permission_that_grants_contact_access() -> None:
    """An administrator can revoke access. Granting needs both members."""
    granting = {code for code in MATCHMAKING_INTERACTION_PERMISSIONS if code.endswith(".grant")}
    assert granting == set()
    assert "matchmaking.contact_exchange.revoke" in MATCHMAKING_INTERACTION_PERMISSIONS


def test_the_operator_role_holds_no_sensitive_permission() -> None:
    operator = ROLE_PERMISSIONS["interaction_operator"]
    for sensitive in (
        "matchmaking.interactions.sensitive.read",
        "matchmaking.invitations.content.read",
        "matchmaking.contact_exchange.sensitive.read",
        "matchmaking.matches.freeze",
        "matchmaking.contact_exchange.revoke",
    ):
        assert sensitive not in operator


def test_the_support_role_holds_no_sensitive_permission() -> None:
    support = ROLE_PERMISSIONS["interaction_support"]
    assert not any("sensitive" in code or "content" in code for code in support)


def test_the_safety_reviewer_can_investigate_but_not_replay_events() -> None:
    reviewer = ROLE_PERMISSIONS["interaction_safety_reviewer"]
    assert "matchmaking.interactions.sensitive.read" in reviewer
    assert "matchmaking.events.replay" not in reviewer


@pytest.mark.parametrize("schema", [AdminSensitiveReadRequest, AdminInvalidateRequest])
def test_every_privileged_body_requires_a_stated_purpose(schema: type) -> None:
    """A purpose is a required field, not an optional note."""
    assert "purpose" in schema.model_fields
    assert schema.model_fields["purpose"].is_required()


@pytest.mark.parametrize("handler_name", ["pair_sensitive_view", "invitation_content"])
def test_every_sensitive_read_takes_a_purpose_carrying_body(handler_name: str) -> None:
    """The handler cannot be called without the body that carries the purpose.

    Read from the module source rather than the live signature: FastAPI's
    dependency defaults are not safely introspectable outside a request.
    """
    handler = getattr(admin_router, handler_name)
    source = inspect.getsource(handler)
    assert "payload: AdminSensitiveReadRequest" in source
    assert "purpose=payload.purpose" in source
