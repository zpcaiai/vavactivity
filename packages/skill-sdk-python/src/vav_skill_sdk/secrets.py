"""Opaque, expiring secret handles; permanent credentials never enter Skill input."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from vav_skill_sdk.context import SkillContext


class TemporarySecretHandle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    handle: str = Field(min_length=16, max_length=512)
    reference: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,127}$")
    expires_at: datetime


class SkillSecretBroker(Protocol):
    async def issue(self, reference: str, context: SkillContext) -> TemporarySecretHandle: ...
