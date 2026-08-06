"""Local harness that preserves production validation and authority semantics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Generic, TypeVar
from uuid import uuid4

from pydantic import BaseModel

from vav_skill_sdk.context import SkillContext, SkillPrincipal
from vav_skill_sdk.events import SkillEvent
from vav_skill_sdk.secrets import TemporarySecretHandle
from vav_skill_sdk.skill import Skill

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


class FakeClock:
    def __init__(self, now: datetime | None = None) -> None:
        self._now = now or datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


class FakeEventBus:
    def __init__(self) -> None:
        self.events: list[SkillEvent] = []

    async def publish(self, event: SkillEvent) -> None:
        self.events.append(event)


class FakeSecretProvider:
    def __init__(self, allowed: frozenset[str] = frozenset()) -> None:
        self.allowed = allowed

    async def issue(self, reference: str, context: SkillContext) -> TemporarySecretHandle:
        if reference not in self.allowed or f"secrets.{reference}.read" not in context.permissions:
            raise PermissionError("secret reference is not granted")
        return TemporarySecretHandle(
            handle=f"temporary-handle-{reference}",
            reference=reference,
            expires_at=context.deadline,
        )


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
    def context(
        *,
        permissions: frozenset[str] = frozenset(),
        clock: FakeClock | None = None,
    ) -> SkillContext:
        now = clock.now() if clock else datetime.now(UTC)
        return SkillContext(
            execution_id=uuid4(),
            installation_id=uuid4(),
            principal=SkillPrincipal(principal_type="service", principal_id="skill-testkit"),
            locale="zh-CN",
            timezone="Asia/Shanghai",
            deadline=now + timedelta(seconds=30),
            permissions=permissions,
            request_id=uuid4(),
            trace_id=uuid4().hex,
        )

    async def execute(self, input_data: dict[str, object], *, context: SkillContext) -> OutputT:
        parsed_input = self._input_model.model_validate(input_data)
        output = await self._skill.execute(parsed_input, context)
        return self._output_model.model_validate(output, from_attributes=True)
