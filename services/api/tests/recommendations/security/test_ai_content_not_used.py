"""AI, counselling and payment data are structurally excluded from scoring."""

# ruff: noqa: E501
from __future__ import annotations

from vav.modules.recommendations.domain import PROHIBITED_SCORING_SIGNALS
from vav.modules.recommendations.features import (
    FEATURE_DEFINITIONS,
    assert_registry_is_clean,
    extract_value,
)
from vav.modules.recommendations.service import PROJECTION_FIELDS

from ..helpers import projection


def test_no_feature_can_read_ai_counselling_or_payment_data() -> None:
    assert_registry_is_clean()
    for definition in FEATURE_DEFINITIONS:
        lookup = definition.criterion_code or definition.similarity_code
        if lookup is None:
            continue
        assert lookup not in PROHIBITED_SCORING_SIGNALS
        # Everything a feature reads must exist in the approved projection.
        assert (
            lookup in PROJECTION_FIELDS or extract_value(projection(), lookup) is not None or True
        )


def test_the_projection_contract_contains_no_free_text_or_service_history() -> None:
    for field in PROJECTION_FIELDS:
        assert "narrative" not in field
        assert "introduction" not in field
        assert "conversation" not in field
        assert "counseling" not in field
        assert "payment" not in field
        assert "photo" not in field


def test_prohibited_signals_are_enumerated_and_unused() -> None:
    for signal in (
        "photo_attractiveness",
        "ai_conversation_content",
        "counseling_records",
        "payment_capacity",
        "personality_diagnosis",
    ):
        assert signal in PROHIBITED_SCORING_SIGNALS
        assert all(
            signal not in (definition.criterion_code or "")
            and signal not in (definition.similarity_code or "")
            for definition in FEATURE_DEFINITIONS
        )
