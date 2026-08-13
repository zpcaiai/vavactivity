"""Request payloads for the capacity and waitlist guard (ACT-003)."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

_STRICT = ConfigDict(extra="forbid")


class _Base(BaseModel):
    model_config = _STRICT


# ---------------------------------------------------------------------------
# Member-facing
# ---------------------------------------------------------------------------


class SeatReservationRequest(_Base):
    """Ask for seats on a ticket type; may resolve to a waitlist place."""

    ticket_type_id: UUID
    seats: Annotated[int, Field(ge=1, le=20)] = 1
    #: Accept a waitlist place if the ticket type is full. Sending ``false``
    #: means "seat or nothing"; the caller then gets ``CAPACITY_FULL`` rather
    #: than a queue place they did not ask for.
    accept_waitlist: bool = True
    #: Client-supplied idempotency key. A retried reservation with the same key
    #: returns the original outcome instead of taking a second seat.
    idempotency_key: Annotated[str, Field(min_length=8, max_length=128)]


class OfferResponseRequest(_Base):
    """Answer a waitlist promotion offer before its deadline."""

    response: Literal["accept", "decline"]


class WaitlistWithdrawRequest(_Base):
    reason: Annotated[str, Field(max_length=500)] | None = None


# ---------------------------------------------------------------------------
# Administrative
# ---------------------------------------------------------------------------


class CapacityAdjustRequest(_Base):
    """Change a ticket type's cap.

    A finite capacity of zero means sold out; unlimited is an explicit,
    catalog-derived mode rather than a magic number. A reason is mandatory in
    both directions: raising a cap changes who gets in,
    lowering one is refused outright if it would put the ticket type below the
    seats already sold (``CAPACITY_BELOW_CONFIRMED``) - the guard never resolves
    that by cancelling somebody's registration on an administrator's behalf.
    """

    capacity: Annotated[int, Field(ge=0, le=1_000_000)]
    #: Optional optimistic assertion of the catalog-derived mode. It does not
    #: switch modes; it prevents a stale admin screen from applying a bounded
    #: value after the SKU has become unlimited (or vice versa).
    is_unlimited: bool | None = None
    waitlist_capacity: Annotated[int, Field(ge=0, le=1_000_000)] | None = None
    reason: Annotated[str, Field(min_length=4, max_length=1000)]

    @model_validator(mode="after")
    def validate_unlimited_placeholder(self) -> CapacityAdjustRequest:
        if self.is_unlimited is True and self.capacity != 0:
            raise ValueError("unlimited capacity must use zero as its numeric placeholder")
        return self


class SalesStateRequest(_Base):
    sales_state: Literal["open", "closed", "suspended"]
    reason: Annotated[str, Field(min_length=4, max_length=1000)]


class PromotionRoundRequest(_Base):
    """Run a promotion round by hand, e.g. after a bulk cancellation."""

    ticket_type_id: UUID
    #: Promote smaller parties past a blocking large one. Off by default: it
    #: fills the room at the cost of queue order, which members can see.
    allow_skip_oversized: bool = False
    max_offers: Annotated[int, Field(ge=1, le=200)] = 50
    dry_run: bool = False


class OfferSweepRequest(_Base):
    """Expire timed-out promotion offers and release their held seats."""

    ticket_type_id: UUID | None = None
    limit: Annotated[int, Field(ge=1, le=1000)] = 200
