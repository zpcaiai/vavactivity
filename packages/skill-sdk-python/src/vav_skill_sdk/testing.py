"""Local harness that preserves production validation and authority semantics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Generic, TypeVar
from uuid import uuid4

from pydantic import BaseModel

from vav_skill_sdk.context import SkillContext, SkillPrincipal
from vav_skill_sdk.skill import Skill

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


class SkillHarness(Generic[InputT, OutputT]):
    def __init__(
        self,
        skill: Skill[InputT, OutputT],
        input_model: type[InputT],
        output_model: type[OutputT],
    ) -> None:
        self._skill = skill
        self._input_model = input_model
        self._output_model = output_model

    @staticmethod
    def context(*, permissions: frozenset[str] = frozenset()) -> SkillContext:
        return SkillContext(
            execution_id=uuid4(),
            installation_id=uuid4(),
            principal=SkillPrincipal(principal_type="service", principal_id="skill-testkit"),
            locale="zh-CN",
            timezone="Asia/Shanghai",
            deadline=datetime.now(UTC) + timedelta(seconds=30),
            permissions=permissions,
            request_id=uuid4(),
            trace_id=uuid4().hex,
        )

    async def execute(self, input_data: dict[str, object], *, context: SkillContext) -> OutputT:
        parsed_input = self._input_model.model_validate(input_data)
        output = await self._skill.execute(parsed_input, context)
        return self._output_model.model_validate(output, from_attributes=True)
