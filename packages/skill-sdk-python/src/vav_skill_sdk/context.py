"""Immutable execution identity and authority passed to Skills."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SkillPrincipal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    principal_type: Literal["user", "admin", "service", "agent", "event", "schedule"]
    principal_id: str = Field(min_length=1, max_length=255)
    organization_id: UUID | None = None


class SkillContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_id: UUID
    installation_id: UUID
    actor_user_id: UUID | None = None
    principal: SkillPrincipal
    locale: str = Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    timezone: str = Field(min_length=1, max_length=64)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)
    deadline: datetime
    permissions: frozenset[str] = frozenset()
    capability_grants: frozenset[str] = frozenset()
    request_id: UUID
    trace_id: str = Field(pattern=r"^[0-9a-f]{16,64}$")

    @model_validator(mode="after")
    def deadline_has_timezone(self) -> "SkillContext":
        if self.deadline.tzinfo is None:
            raise ValueError("deadline must be timezone-aware")
        return self
