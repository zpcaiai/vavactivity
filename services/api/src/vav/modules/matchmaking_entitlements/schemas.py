"""Request payloads for matchmaking eligibility and entitlements (B12)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RelationshipStatusRequest(_Base):
    """Self-declared status.

    ``couple_binding`` is deliberately not accepted here: only the couple
    module may write that source, so a member cannot fake a binding.
    """

    status: Literal["undisclosed", "single", "dating", "engaged", "married", "separated", "widowed"]
    reason: Annotated[str, Field(max_length=500)] | None = None


class AdminRelationshipStatusRequest(_Base):
    status: Literal["undisclosed", "single", "dating", "engaged", "married", "separated", "widowed"]
    reason: Annotated[str, Field(min_length=4, max_length=1000)]


class EntitlementAdjustRequest(_Base):
    delta: Annotated[int, Field(ge=-10, le=10)]
    note: Annotated[str, Field(min_length=4, max_length=1000)]
    #: Supply a stable key when replaying a failed adjustment so the same
    #: correction cannot be applied twice.
    idempotency_key: Annotated[str, Field(max_length=255)] | None = None


class DeliveryHistoryResetRequest(_Base):
    reason: Annotated[str, Field(min_length=4, max_length=1000)]


class DisclaimerRequest(_Base):
    disclaimer_code: Annotated[str, Field(min_length=2, max_length=128, pattern=r"^[a-z][a-z0-9_-]*$")]
    semantic_version: Annotated[str, Field(min_length=1, max_length=32)]
    locale: Annotated[str, Field(min_length=2, max_length=16)]
    body: Annotated[str, Field(min_length=1, max_length=8000)]


class ArrivalJobRequest(_Base):
    """``opportunity_key`` identifies the pool change being announced."""

    opportunity_key: Annotated[str, Field(min_length=1, max_length=128)]
