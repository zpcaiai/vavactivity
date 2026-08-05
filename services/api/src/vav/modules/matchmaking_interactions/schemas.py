"""Request bodies for member interaction writes."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class SkipRequest(BaseModel):
    skip_type: str = Field(default="not_now")
    reason_code: str | None = Field(default=None, max_length=128)
    #: Free text stays encrypted at rest and is never shown to the other
    #: member, so the only limit here is length.
    reason_details: str | None = Field(default=None, max_length=2000)


class CloseMatchRequest(BaseModel):
    reason_code: str | None = Field(default=None, max_length=128)


class InvitationRequest(BaseModel):
    message: str | None = Field(default=None, max_length=2000)


class InvitationDecisionRequest(BaseModel):
    #: Optimistic lock. A client that read the invitation before it was
    #: cancelled or expired is refused rather than allowed to overwrite it.
    expected_invitation_version: int | None = Field(default=None, ge=1)


class DeclineInvitationRequest(InvitationDecisionRequest):
    reason_code: str | None = Field(default=None, max_length=128)


class ContactConsentRequest(BaseModel):
    selected_contact_point_ids: list[UUID] = Field(default_factory=list)
    #: Choosing to stay on the platform is a complete answer, not a refusal to
    #: answer, and it opens nothing.
    platform_only: bool = Field(default=False)


class ContactRevealTokenRequest(BaseModel):
    contact_point_id: UUID


class ContactRevealRequest(BaseModel):
    reveal_token: str = Field(min_length=8, max_length=256)


class AdminInvalidateRequest(BaseModel):
    reason_code: str = Field(max_length=128)
    purpose: str = Field(min_length=4, max_length=128)


class AdminSensitiveReadRequest(BaseModel):
    purpose: str = Field(min_length=4, max_length=128)
