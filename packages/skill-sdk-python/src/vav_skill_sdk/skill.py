"""Protocols implemented by executable Skills."""

from typing import Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel

from vav_skill_sdk.context import SkillContext

InputT = TypeVar("InputT", bound=BaseModel, contravariant=True)
OutputT = TypeVar("OutputT", bound=BaseModel, covariant=True)


class Skill(Protocol, Generic[InputT, OutputT]):
    async def execute(self, input_data: InputT, context: SkillContext) -> OutputT: ...


class CommandSkill(Skill[InputT, OutputT], Protocol):
    idempotency_required: Literal[True]

    async def compensate(self, execution_id: str, context: SkillContext) -> bool: ...
