from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from vav_skill_sdk.testing import SkillHarness


class EchoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str


class EchoOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str


class EchoSkill:
    async def execute(self, input_data: EchoInput, context: object) -> EchoOutput:
        return EchoOutput(message=input_data.message)


@pytest.mark.asyncio
async def test_harness_validates_both_sides() -> None:
    harness = SkillHarness(EchoSkill(), EchoInput, EchoOutput)
    result = await harness.execute({"message": "hello"}, context=harness.context())
    assert result.message == "hello"
    with pytest.raises(ValidationError):
        await harness.execute(
            {"message": "hello", "secret": "no"}, context=harness.context()
        )


def test_context_rejects_naive_deadline() -> None:
    context = SkillHarness.context().model_dump()
    context["deadline"] = datetime(2026, 1, 1)
    with pytest.raises(ValidationError, match="timezone-aware"):
        SkillHarness.context().__class__.model_validate(context)
