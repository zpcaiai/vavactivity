"""Versioned event contracts exposed to Skills without broker credentials."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SkillEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: UUID
    event_type: str = Field(pattern=r"^[a-z][a-z0-9_.-]+\.v[1-9]\d*$", max_length=160)
    occurred_at: datetime
    payload: dict[str, Any]
    causation_id: UUID | None = None
    depth: int = Field(default=0, ge=0, le=16)


class SkillEventBus(Protocol):
    async def publish(self, event: SkillEvent) -> None: ...
