"""Request payloads for the onsite check-in operations module (CHK-002)."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

_STRICT = ConfigDict(extra="forbid")


class _Base(BaseModel):
    model_config = _STRICT


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


class LastFourLookupRequest(_Base):
    """Narrow the guest list by the last four digits of a phone number.

    The field is deliberately *not* called ``phone``: four digits is the only
    accepted input length. A longer fragment would let an operator confirm a
    member's number one query at a time, so the schema rejects it before the
    service ever sees it.
    """

    last_four: Annotated[str, Field(min_length=4, max_length=4, pattern=r"^\d{4}$")]
    session_id: UUID | None = None
    device_reference: Annotated[str, Field(max_length=128)] = "unknown-device"

    @field_validator("last_four")
    @classmethod
    def _digits_only(cls, value: str) -> str:
        if not value.isdigit():
            raise ValueError("last_four must be four digits")
        return value


class ChoiceSelectRequest(_Base):
    """Pick one candidate out of an ambiguous lookup.

    ``choice_token`` is an opaque HMAC minted for this lookup only; there is no
    registration id or user id anywhere in this payload, by design.
    """

    lookup_id: UUID
    choice_token: Annotated[str, Field(min_length=16, max_length=64, pattern=r"^[0-9a-f]+$")]
    #: What the operator actually verified against the member in front of them.
    #: Recorded on the audit row so an "I never gave them my name" dispute has
    #: an answer.
    discriminator_kind: Literal["name_initial", "registration_suffix", "both"] = "both"


# ---------------------------------------------------------------------------
# Check-in
# ---------------------------------------------------------------------------


class ScanRequest(_Base):
    """A scan of a check-in credential (QR/NFC), before confirmation."""

    credential_token: Annotated[str, Field(min_length=8, max_length=512)]
    session_id: UUID | None = None
    method: Literal["qr", "nfc", "manual", "phone_last_four"] = "qr"
    device_reference: Annotated[str, Field(max_length=128)] = "unknown-device"


class ConfirmCheckinRequest(_Base):
    """The explicit second tap that actually writes attendance.

    Two steps, not one: an accidental brush of a large onsite touch target must
    not be able to check somebody in. The token is short-lived and bound to the
    operator who started the flow.
    """

    lookup_id: UUID
    confirmation_token: Annotated[str, Field(min_length=16, max_length=64, pattern=r"^[0-9a-f]+$")]
    session_id: UUID | None = None
    method: Literal["qr", "nfc", "manual", "phone_last_four"] = "manual"
    device_reference: Annotated[str, Field(max_length=128)] = "unknown-device"
    #: Required when the check-in falls outside the configured window. Sending
    #: it when it is not needed is harmless and still audited.
    override_reason: Annotated[str, Field(min_length=4, max_length=1000)] | None = None


class UndoCheckinRequest(_Base):
    """Undo a check-in inside the short operator window."""

    reason: Annotated[str, Field(min_length=4, max_length=1000)]
    device_reference: Annotated[str, Field(max_length=128)] = "unknown-device"


class RevokeCheckinRequest(_Base):
    """Revoke a check-in after the undo window, with its own permission."""

    reason: Annotated[str, Field(min_length=4, max_length=1000)]
    mark_no_show: bool = False


# ---------------------------------------------------------------------------
# Administration
# ---------------------------------------------------------------------------


class WindowPolicyRequest(_Base):
    early_minutes: Annotated[int, Field(ge=0, le=1440)] = 60
    late_minutes: Annotated[int, Field(ge=0, le=1440)] = 30


class LastFourBackfillRequest(_Base):
    """Kick off the operator-run backfill described in PATCHES.md.

    The migration deliberately backfills nothing: the stored contact value is
    encrypted, so deriving a last-four requires the decryption key and a job
    that is allowed to touch plaintext. That job is explicitly requested here,
    is permission-gated, and is rate-limited by ``batch_size``.
    """

    batch_size: Annotated[int, Field(ge=1, le=5000)] = 500
    salt_version: Annotated[str, Field(min_length=1, max_length=16, pattern=r"^v\d+$")] = "v1"
    dry_run: bool = True
