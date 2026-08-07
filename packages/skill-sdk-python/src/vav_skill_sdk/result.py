"""Stable success result returned across every Skill runtime adapter."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SkillResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    data: dict[str, Any]
    warnings: tuple[str, ...] = ()
    metadata: dict[str, str] = Field(default_factory=dict)
