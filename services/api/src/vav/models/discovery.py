"""Discovery ORM models (B13: GEO-001 city preference, MAP-001 venues, SHARE-001 sharing).

These models exist for schema documentation and metadata only; the service layer
uses raw SQL through ``sqlalchemy.text()``. Table names keep the ``activity_`` /
``discovery_`` / ``member_`` prefixes already used elsewhere so the schema stays
navigable.

Two privacy notes are load-bearing here:

* :class:`DiscoveryIpHint` deliberately has no column that could hold an IP
  address or a coordinate. The only IP-derived value is a salted, truncated
  marker (GEO-001).
* :class:`ActivityVenueLocation` keeps ``manual_address`` as a NOT NULL column
  separate from ``formatted_address``, which is what makes "a geocoding failure
  preserves the manually entered address" structurally true (MAP-001).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from vav.models.activities import created_at, updated_at, uuid_pk
from vav.models.base import Base

# ---------------------------------------------------------------------------
# GEO-001 city preference
# ---------------------------------------------------------------------------


class MemberCityPreference(Base):
    """The member's *manual* city choice. IP never writes here (GEO-001)."""

    __tablename__ = "member_city_preferences"

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    city_code: Mapped[str | None] = mapped_column(String(32))
    allow_ip_suggestion: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    #: NULL whenever ``city_code`` is NULL. A confirmed timestamp is what marks
    #: the value as a deliberate member choice rather than an inferred one.
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class DiscoveryIpHint(Base):
    """The only permitted record of an IP-derived location.

    A coarse city code plus a salted, truncated marker. There is intentionally
    no ``ip_address``, ``latitude``, ``longitude`` or ``postal_code`` column:
    the schema itself makes the GEO-001 rule impossible to violate by accident.
    """

    __tablename__ = "discovery_ip_hints"

    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    city_code: Mapped[str | None] = mapped_column(String(32))
    ip_marker: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = created_at()


# ---------------------------------------------------------------------------
# MAP-001 venue locations and provider configuration
# ---------------------------------------------------------------------------


class ActivityVenueLocation(Base):
    """A venue address plus its optional normalized geocoding result."""

    __tablename__ = "activity_venue_locations"

    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), primary_key=True
    )
    #: NOT NULL: the operator's own text is never blanked by a failed geocode.
    manual_address: Mapped[str] = mapped_column(Text, nullable=False)
    formatted_address: Mapped[str | None] = mapped_column(Text)
    country_code: Mapped[str | None] = mapped_column(String(2))
    region_code: Mapped[str | None] = mapped_column(String(32))
    city_code: Mapped[str | None] = mapped_column(String(32))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    provider: Mapped[str | None] = mapped_column(String(32))
    provider_place_ref: Mapped[str | None] = mapped_column(String(255))
    geocode_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'skipped'")
    )
    failure_code: Mapped[str | None] = mapped_column(String(64))
    geocoded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class MapProviderConfig(Base):
    """Which provider serves a country. Credentials live in settings, not here."""

    __tablename__ = "map_provider_configs"

    country_code: Mapped[str] = mapped_column(String(2), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    updated_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


# ---------------------------------------------------------------------------
# SHARE-001 share cards, links and resolutions
# ---------------------------------------------------------------------------


class ActivityShareCard(Base):
    """A deterministic share card payload, keyed by activity and card version."""

    __tablename__ = "activity_share_cards"
    __table_args__ = (UniqueConstraint("activity_id", "card_version"),)

    id: Mapped[UUID] = uuid_pk()
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    card_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    #: SHA-256 of the canonical payload. Same event + version => same value,
    #: which is what makes the card snapshot-testable.
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    cover_is_fallback: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ActivityShareLink(Base):
    """A signed short link. Revoked rather than deleted so support can explain it."""

    __tablename__ = "activity_share_links"
    __table_args__ = (UniqueConstraint("short_code"),)

    id: Mapped[UUID] = uuid_pk()
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    share_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    short_code: Mapped[str] = mapped_column(String(32), nullable=False)
    signature: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Always the canonical ``/events/{id}`` URL, so the QR and the short link
    #: resolve to the one place that enforces access control.
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ActivityShareResolution(Base):
    """One resolution of a short link. Counts scans without storing a visitor."""

    __tablename__ = "activity_share_resolutions"

    id: Mapped[UUID] = uuid_pk()
    activity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id"), nullable=False
    )
    short_code: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = created_at()


class DiscoveryAudit(Base):
    """Append-only audit of venue, provider and share-link administration."""

    __tablename__ = "discovery_audits"

    id: Mapped[UUID] = uuid_pk()
    subject_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = created_at()
