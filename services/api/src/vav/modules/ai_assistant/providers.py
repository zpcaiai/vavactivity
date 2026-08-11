from __future__ import annotations

import json
import re
from typing import Any, Protocol, TypeVar

import httpx
from pydantic import BaseModel

from vav.modules.ai_assistant.classification import classify_message
from vav.modules.ai_assistant.safety import assess_risk
from vav.modules.ai_assistant.schemas import MessageClassification

StructuredT = TypeVar("StructuredT", bound=BaseModel)

GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_SYSTEM_INSTRUCTION = """You are Hanna, VAV's AI relationship education assistant.
You are an AI service, not Hanna personally and not an emergency, medical, legal, or licensed
counseling service. Respond in the requested locale. Be warm but concise: reflect the user's
situation, identify one possible blind spot without shaming, and offer one or two concrete next
steps. Respect consent, autonomy, privacy, and the other person's right to decline or withdraw.
Never diagnose, promise outcomes, expose private data, invent tool results, or claim a source that
is not included in the authorized context. If the context indicates danger or professional scope,
prioritize immediate human or emergency support. Return only the user-facing response text."""


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


class AiProviderError(RuntimeError):
    """Safe provider failure that never includes credentials or upstream response bodies."""


class AiProviderConfigurationError(AiProviderError):
    pass


class AiProviderContentBlockedError(AiProviderError):
    pass


class DeterministicLocalProvider:
    """Auditable development/evaluation provider; forbidden in production."""

    provider_code = "deterministic_local"
    model_name = "hanna-rules"
    model_revision = "1.0.0"

    async def generate_text(self, *, task_type: str, input_data: dict[str, Any]) -> str:
        message = str(input_data.get("message", ""))
        if task_type == "conversation_summary":
            return message[:2000]
        if task_type == "response_generation":
            return str(input_data.get("draft_response", message))
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


class GeminiProvider:
    """Gemini text adapter; VAV keeps safety, classification, and tool authorization local."""

    provider_code = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str = "gemini-3.6-flash",
        timeout_seconds: float = 45,
        max_output_tokens: int = 2000,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key.strip():
            raise AiProviderConfigurationError("Gemini API key is not configured")
        if not re.fullmatch(r"[A-Za-z0-9._-]+", model_name):
            raise AiProviderConfigurationError("Gemini model name is invalid")
        self._api_key = api_key
        self.model_name = model_name
        self.model_revision = model_name
        self._timeout = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._client = client

    @property
    def _endpoint(self) -> str:
        return f"{GEMINI_API_BASE_URL}/models/{self.model_name}:generateContent"

    async def _generate(self, input_data: dict[str, Any]) -> str:
        request_body = {
            "systemInstruction": {"parts": [{"text": GEMINI_SYSTEM_INSTRUCTION}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": json.dumps(
                                input_data,
                                ensure_ascii=False,
                                sort_keys=True,
                                default=str,
                            )
                        }
                    ],
                }
            ],
            "generationConfig": {"maxOutputTokens": self._max_output_tokens},
            "store": False,
        }

        async def post(client: httpx.AsyncClient) -> httpx.Response:
            return await client.post(
                self._endpoint,
                headers={"x-goog-api-key": self._api_key},
                json=request_body,
            )

        try:
            if self._client is not None:
                response = await post(self._client)
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await post(client)
            response.raise_for_status()
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise AiProviderError("Gemini request failed") from exc
        except httpx.HTTPStatusError as exc:
            raise AiProviderError(f"Gemini returned HTTP {exc.response.status_code}") from exc

        try:
            payload = response.json()
            candidates = payload.get("candidates") or []
            parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
            text = "".join(
                str(part.get("text", "")) for part in parts if isinstance(part, dict)
            ).strip()
        except (AttributeError, IndexError, TypeError, ValueError) as exc:
            raise AiProviderError("Gemini returned an invalid response") from exc
        if text:
            return text
        if payload.get("promptFeedback", {}).get("blockReason"):
            raise AiProviderContentBlockedError("Gemini blocked the prompt")
        raise AiProviderError("Gemini returned no response text")

    async def generate_text(self, *, task_type: str, input_data: dict[str, Any]) -> str:
        if task_type != "response_generation":
            return await deterministic_provider.generate_text(
                task_type=task_type, input_data=input_data
            )
        return await self._generate(input_data)

    async def generate_structured(
        self,
        *,
        task_type: str,
        schema: type[StructuredT],
        input_data: dict[str, Any],
    ) -> StructuredT:
        return await deterministic_provider.generate_structured(
            task_type=task_type,
            schema=schema,
            input_data=input_data,
        )

    async def generate_tool_calls(
        self, *, task_type: str, input_data: dict[str, Any]
    ) -> list[dict[str, Any]]:
        return await deterministic_provider.generate_tool_calls(
            task_type=task_type,
            input_data=input_data,
        )


def configured_provider(settings: Any) -> AiModelProvider:
    provider_code = str(settings.ai_model_provider).strip().casefold()
    if provider_code == "deterministic_local":
        return deterministic_provider
    if provider_code == "gemini":
        secret = settings.ai_provider_api_key
        api_key = secret.get_secret_value() if secret is not None else ""
        return GeminiProvider(
            api_key=api_key,
            model_name=settings.ai_model_name,
            timeout_seconds=settings.ai_turn_timeout_seconds,
            max_output_tokens=settings.ai_turn_max_output_tokens,
        )
    raise AiProviderConfigurationError(f"Unsupported AI model provider: {provider_code}")
