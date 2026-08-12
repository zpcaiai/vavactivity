"""Request payloads for the attendee preview and follow graph (ATT-001 / SOC-001)."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

_STRICT = ConfigDict(extra="forbid")


class _Base(BaseModel):
    model_config = _STRICT


# ---------------------------------------------------------------------------
# ATT-001 attendee preview consent
# ---------------------------------------------------------------------------


class PreviewConsentRequest(_Base):
    """Record a member's answer to the attendee-preview prompt.

    There is no default here on purpose: the caller must state the decision.
    The *absence* of a record already means "not shown" (DEC-002), so a missing
    field must never be interpretable as consent.
    """

    decision: Literal["granted", "declined", "withdrawn"]
    #: Optional free-text the member typed when withdrawing. Stored encrypted.
    note: Annotated[str, Field(max_length=1000)] | None = None


class PreviewIntroRequest(_Base):
    """The optional one-line intro rendered next to the avatar."""

    intro_line: Annotated[str, Field(max_length=60)] | None = None


class PreviewQuery(_Base):
    limit: Annotated[int, Field(ge=1, le=50)] = 12
    #: Post-event surfaces set this to drop no-shows and revoked check-ins.
    exclude_absent: bool = False


# ---------------------------------------------------------------------------
# SOC-001 follow graph
# ---------------------------------------------------------------------------


class FollowRequest(_Base):
    """Follow a member.

    Deliberately carries no ``kind`` field: this endpoint creates a *follow* and
    nothing else. Likes and want-to-meet are separate resources with separate
    permissions and separate visibility (SOC-001).
    """

    user_id: UUID


class WantToMeetRequest(_Base):
    """Express event-scoped intent to meet someone. Not a follow, not a like."""

    user_id: UUID
    activity_id: UUID


class NotificationPreferenceRequest(_Base):
    """Toggle the ``followed_user_registered`` notification."""

    followed_user_registered: bool = True


class AdminConsentOverrideRequest(_Base):
    """Administratively withdraw a member's preview consent.

    Only withdrawal is possible from the admin side. An operator can never grant
    consent on a member's behalf, because that would defeat the opt-in default
    (DEC-002).
    """

    registration_id: UUID
    reason: Annotated[str, Field(min_length=4, max_length=1000)]
