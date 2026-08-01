from __future__ import annotations

from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from vav.modules.ai_assistant.classification import classify_message
from vav.modules.ai_assistant.safety import assess_risk
from vav.modules.ai_assistant.schemas import MessageClassification

StructuredT = TypeVar("StructuredT", bound=BaseModel)


class AiModelProvider(Protocol):
    provider_code: str
    model_name: str
    model_revision: str

    async def generate_text(self, *, task_type: str, input_data: dict[str, Any]) -> str: ...

    async def generate_structured(
        self,
        *,
        task_type: str,
        schema: type[StructuredT],
        input_data: dict[str, Any],
    ) -> StructuredT: ...

    async def generate_tool_calls(
        self, *, task_type: str, input_data: dict[str, Any]
    ) -> list[dict[str, Any]]: ...


class DeterministicLocalProvider:
    """Auditable development/evaluation provider; forbidden in production."""

    provider_code = "deterministic_local"
    model_name = "hanna-rules"
    model_revision = "1.0.0"

    async def generate_text(self, *, task_type: str, input_data: dict[str, Any]) -> str:
        message = str(input_data.get("message", ""))
        if task_type == "conversation_summary":
            return message[:2000]
        return message

    async def generate_structured(
        self,
        *,
        task_type: str,
        schema: type[StructuredT],
        input_data: dict[str, Any],
    ) -> StructuredT:
        message = str(input_data.get("message", ""))
        if task_type == "message_classification" and schema is MessageClassification:
            return schema.model_validate(classify_message(message).model_dump())
        if task_type == "risk_classification":
            return schema.model_validate(assess_risk(message).model_dump())
        raise ValueError(f"Unsupported deterministic structured task: {task_type}")

    async def generate_tool_calls(
        self, *, task_type: str, input_data: dict[str, Any]
    ) -> list[dict[str, Any]]:
        if task_type != "tool_planning":
            raise ValueError(f"Unsupported deterministic tool task: {task_type}")
        message = str(input_data.get("message", "")).casefold()
        calls: list[dict[str, Any]] = []
        for code, terms in (
            ("search_published_activities", ("活动", "activity")),
            ("search_published_courses", ("课程", "course")),
            ("search_counseling_services", ("辅导", "咨询", "counseling", "mentor")),
            ("get_user_course_progress", ("学习进度", "course progress")),
            ("get_user_entitlements", ("已购", "权益", "entitlement")),
            ("get_user_upcoming_appointments", ("预约", "appointment")),
        ):
            if any(term in message for term in terms):
                calls.append({"tool_code": code, "arguments": {}})
        return calls[:3]


deterministic_provider = DeterministicLocalProvider()
