from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from vav.common.exceptions import VavError
from vav.modules.ai_assistant.classification import assess_completeness, classify_message
from vav.modules.ai_assistant.tooling import TOOL_REGISTRY, registry_version, validate_arguments


def test_service_request_is_structured_and_uses_current_data() -> None:
    classification = classify_message("平台现在有哪些辅导服务和可预约时段？")
    assert classification.primary_topic.value == "service_navigation"
    assert classification.requires_current_service_data is True
    assert classification.requires_knowledge_retrieval is False


def test_short_ambiguous_message_requests_at_most_two_clarifications() -> None:
    classification = classify_message("怎么办")
    completeness = assess_completeness("怎么办", classification)
    assert completeness.sufficient_for_response is False
    assert 1 <= len(completeness.clarifying_questions) <= 2


def test_tool_registry_is_versioned_and_write_tools_require_confirmation() -> None:
    assert registry_version() == "hanna-tools-1.0.0"
    write_tool = TOOL_REGISTRY["create_counseling_referral"]
    assert write_tool.confirmation_required is True
    assert write_tool.idempotency_required is True
    with pytest.raises(ValidationError):
        validate_arguments(
            write_tool,
            {"user_id": "10000000-0000-0000-0000-000000000001"},
            current_user_id=UUID("10000000-0000-0000-0000-000000000001"),
        )


def test_tool_arguments_reject_cross_user_access() -> None:
    with pytest.raises(VavError) as error:
        validate_arguments(
            TOOL_REGISTRY["get_user_course_progress"],
            {"user_id": "20000000-0000-0000-0000-000000000002"},
            current_user_id=UUID("10000000-0000-0000-0000-000000000001"),
        )
    assert error.value.code == "AI_TOOL_CROSS_USER_FORBIDDEN"
