"""Request payloads for couple binding and SCOPE assessments (B16)."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InvitationCreateRequest(_Base):
    """Half of a two-sided binding. Sending this binds nobody (COUPLE-001)."""

    invitee_user_id: UUID
    relationship_kind: Literal["dating", "engaged", "married"] = "dating"
    #: Private note to the invitee. Stored encrypted, never in an outbox payload.
    note: Annotated[str, Field(max_length=500)] | None = None


class InvitationRespondRequest(_Base):
    """Only the invitee may send this; see ``ensure_invitation_actor``."""

    decision: Literal["accept", "reject"]
    reason_code: Annotated[str, Field(max_length=64, pattern=r"^[a-z][a-z0-9_]*$")] | None = None


class UnbindRequest(_Base):
    reason: Annotated[str, Field(max_length=1000)] | None = None


class AdminUnbindRequest(_Base):
    """An administrative unbind overrides two members' stated relationship."""

    reason: Annotated[str, Field(min_length=4, max_length=1000)]


class ScopeVersionRequest(_Base):
    version_code: Annotated[str, Field(min_length=2, max_length=128, pattern=r"^[a-z][a-z0-9_-]*$")]
    semantic_version: Annotated[str, Field(min_length=1, max_length=32)]
    algorithm_version: Annotated[str, Field(min_length=1, max_length=64)]


class ScopeQuestionRequest(_Base):
    """Administrator-authored question. The platform ships none (DEC-001)."""

    question_code: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")]
    dimension: Literal["support", "communication", "outlook", "partnership", "expectations"]
    prompt_text: Annotated[str, Field(min_length=1, max_length=2000)]
    weight: Annotated[int, Field(ge=1, le=10)] = 1
    scale_min: Annotated[int, Field(ge=1, le=9)] = 1
    scale_max: Annotated[int, Field(ge=2, le=10)] = 5
    reverse_scored: bool = False
    position: Annotated[int, Field(ge=0, le=999)] = 0


class ScopeStartRequest(_Base):
    """Start an assessment for the caller's active binding.

    ``version_id`` is explicit rather than "current", so a pair that starts an
    assessment finishes it on the version they started (SCOPE-001).
    """

    version_id: UUID


class ScopeAnswersRequest(_Base):
    #: question_code -> integer point on that question's own scale.
    answers: dict[Annotated[str, Field(max_length=64)], int]
    #: ``False`` autosaves a draft; ``True`` seals the submission irreversibly.
    submit: bool = False


class ScopeAdviceRequest(_Base):
    """AI narrative attached to a completed report, stored apart from scores."""

    body: Annotated[str, Field(min_length=1, max_length=20000)]
    model_code: Annotated[str, Field(min_length=1, max_length=64)]
    prompt_version: Annotated[str, Field(min_length=1, max_length=64)]
    disclaimer_code: Annotated[str, Field(max_length=128)] = "scope_ai_advice"
