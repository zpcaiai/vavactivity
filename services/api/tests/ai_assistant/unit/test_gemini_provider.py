from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from vav.modules.ai_assistant.providers import (
    AiProviderConfigurationError,
    AiProviderContentBlockedError,
    GeminiProvider,
    configured_provider,
)


@pytest.mark.asyncio
async def test_gemini_generates_text_with_secret_header_and_safe_contract() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["api_key"] = request.headers.get("x-goog-api-key")
        observed["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": "先慢下来，再确认彼此的需要。"}]},
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = GeminiProvider(
            api_key="restricted-test-key",
            model_name="gemini-3.6-flash",
            client=client,
        )
        result = await provider.generate_text(
            task_type="response_generation",
            input_data={"locale": "zh-CN", "user_message": "我该怎么办？"},
        )

    assert result == "先慢下来，再确认彼此的需要。"
    assert observed["api_key"] == "restricted-test-key"
    assert observed["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent"
    )
    body = observed["body"]
    assert isinstance(body, dict)
    assert body["store"] is False
    assert body["generationConfig"] == {"maxOutputTokens": 2000}
    assert "temperature" not in body["generationConfig"]
    assert "Hanna personally" in body["systemInstruction"]["parts"][0]["text"]


@pytest.mark.asyncio
async def test_gemini_reports_safety_block_without_exposing_upstream_payload() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"promptFeedback": {"blockReason": "SAFETY"}, "candidates": []},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = GeminiProvider(api_key="test-key", client=client)
        with pytest.raises(AiProviderContentBlockedError, match="blocked"):
            await provider.generate_text(
                task_type="response_generation",
                input_data={"user_message": "blocked request"},
            )


def test_configured_gemini_provider_requires_a_server_side_key() -> None:
    settings = SimpleNamespace(
        ai_model_provider="gemini",
        ai_provider_api_key=None,
        ai_model_name="gemini-3.6-flash",
        ai_turn_timeout_seconds=45,
        ai_turn_max_output_tokens=2000,
    )
    with pytest.raises(AiProviderConfigurationError, match="key"):
        configured_provider(settings)

    settings.ai_provider_api_key = SecretStr("restricted-key")
    provider = configured_provider(settings)
    assert isinstance(provider, GeminiProvider)
    assert provider.model_name == "gemini-3.6-flash"


def test_gemini_model_name_rejects_path_injection() -> None:
    with pytest.raises(AiProviderConfigurationError, match="model name"):
        GeminiProvider(api_key="test-key", model_name="../other:generateContent")
