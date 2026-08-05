"""Administrative diagnostics stay separate from member-facing output."""

# ruff: noqa: E501
from __future__ import annotations

from uuid import uuid4

import pytest

from vav.modules.recommendations.domain import (
    batch_cache_key,
    candidate_cache_key,
    explanation_cache_key,
    exposure_budget_cache_key,
    pool_cache_key,
    score_cache_key,
)


def test_cache_keys_are_scoped_per_member_and_per_version() -> None:
    viewer, other = uuid4(), uuid4()
    first = candidate_cache_key(viewer, 1, 1, "1.0.0")
    second = candidate_cache_key(other, 1, 1, "1.0.0")
    assert first != second

    # A version change produces a different key, so stale data cannot be served.
    assert candidate_cache_key(viewer, 1, 1, "1.0.0") != candidate_cache_key(viewer, 2, 1, "1.0.0")
    assert candidate_cache_key(viewer, 1, 1, "1.0.0") != candidate_cache_key(viewer, 1, 2, "1.0.0")
    assert candidate_cache_key(viewer, 1, 1, "1.0.0") != candidate_cache_key(viewer, 1, 1, "1.1.0")


def test_batch_and_explanation_keys_include_privacy_and_policy_versions() -> None:
    viewer, batch, item = uuid4(), uuid4(), uuid4()
    assert batch_cache_key(viewer, batch, 1) != batch_cache_key(viewer, batch, 2)
    assert explanation_cache_key(item, "1.0.0") != explanation_cache_key(item, "1.1.0")


def test_pool_and_budget_keys_are_namespaced() -> None:
    assert pool_cache_key(3).startswith("recommendation:pool:")
    assert exposure_budget_cache_key(uuid4(), "2026-08-04").startswith(
        "recommendation:exposure-budget:"
    )
    assert score_cache_key(uuid4(), "1.0.0", "1.0.0").startswith("recommendation:score:")


@pytest.mark.parametrize(
    "trigger",
    [
        "profile_approved",
        "preferences_changed",
        "privacy_changed",
        "block_created",
        "safety_restriction_changed",
        "strategy_rolled_back",
    ],
)
def test_every_sensitive_change_is_a_cache_invalidation_trigger(trigger: str) -> None:
    from vav.modules.recommendations.domain import CACHE_INVALIDATION_TRIGGERS

    assert trigger in CACHE_INVALIDATION_TRIGGERS
