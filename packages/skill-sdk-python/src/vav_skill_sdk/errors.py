"""Safe error contract: internal exceptions and secrets never cross this boundary."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FieldError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field: str = Field(min_length=1, max_length=255)
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,127}$")
    message_safe: str = Field(min_length=1, max_length=500)


class SkillError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,127}$")
    category: Literal[
        "validation",
        "authorization",
        "dependency",
        "conflict",
        "rate_limit",
        "timeout",
        "provider",
        "business",
        "internal",
    ]
    message_safe: str = Field(min_length=1, max_length=1000)
    retryable: bool = False
    field_errors: tuple[FieldError, ...] = ()
    correlation_id: UUID


class SkillExecutionError(Exception):
    """Exception wrapper whose public representation is always a safe contract."""

    def __init__(
        self, error: SkillError, *, internal_context: dict[str, Any] | None = None
    ) -> None:
        super().__init__(error.message_safe)
        self.error = error
        self.internal_context = internal_context or {}
