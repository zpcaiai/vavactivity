"""Request payloads for the discovery module (GEO-001 / MAP-001 / SHARE-001)."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

_STRICT = ConfigDict(extra="forbid")

_CITY_CODE_PATTERN = r"^[A-Za-z0-9_-]{1,32}$"


class _Base(BaseModel):
    model_config = _STRICT


# ---------------------------------------------------------------------------
# GEO-001 city preference
# ---------------------------------------------------------------------------


class CityPreferenceRequest(_Base):
    """Set the member's manual city preference.

    ``None`` clears the preference and returns the member to IP suggestions;
    it does not silently pin them to whatever the IP said at that moment.
    """

    city_code: Annotated[str, Field(pattern=_CITY_CODE_PATTERN)] | None = None
    #: Members who dislike IP hinting entirely can turn the suggestion off.
    allow_ip_suggestion: bool = True


class DiscoveryFeedQuery(_Base):
    """Optional per-request override of the resolved city.

    A one-off override is *not* persisted: the manual preference only changes
    through :class:`CityPreferenceRequest` (GEO-001).
    """

    city_code: Annotated[str, Field(pattern=_CITY_CODE_PATTERN)] | None = None
    limit: Annotated[int, Field(ge=1, le=50)] = 20
    offset: Annotated[int, Field(ge=0, le=10000)] = 0


# ---------------------------------------------------------------------------
# MAP-001 geocoding
# ---------------------------------------------------------------------------


class GeocodeRequest(_Base):
    """Geocode a manually entered venue address.

    ``country_code`` selects the provider. It is supplied by the operator (or
    inherited from the event) rather than sniffed from the address, so provider
    choice is explicit and reviewable.
    """

    manual_address: Annotated[str, Field(min_length=1, max_length=500)]
    country_code: Annotated[str, Field(min_length=2, max_length=2)] = "CN"
    city_code: Annotated[str, Field(pattern=_CITY_CODE_PATTERN)] | None = None


class VenueLocationRequest(_Base):
    """Attach a resolved (or unresolved) location to an activity venue.

    ``place`` is the already-normalized payload. When it is ``None`` the
    manually entered address is stored as-is and the geocode status records the
    failure - the address is never blanked (MAP-001).
    """

    activity_id: UUID
    manual_address: Annotated[str, Field(min_length=1, max_length=500)]
    place: dict[str, Any] | None = None
    failure_code: Annotated[str, Field(max_length=64)] | None = None
    attempted: bool = True


# ---------------------------------------------------------------------------
# SHARE-001 share cards, short links and QR
# ---------------------------------------------------------------------------


class ShareCardRequest(_Base):
    """Create or refresh the share card for a published activity."""

    #: Bump to invalidate a cached card after the event copy changed. The card
    #: payload is deterministic for a given (activity, version) pair.
    card_version: Annotated[int, Field(ge=1, le=10000)] = 1
    #: ``None`` means "no expiry", valid for an evergreen event page.
    ttl_hours: Annotated[int, Field(ge=1, le=8760)] | None = 720
    campaign: Annotated[str, Field(max_length=32, pattern=r"^[a-z0-9_-]+$")] | None = None


class ShareLinkResolveRequest(_Base):
    short_code: Annotated[str, Field(min_length=6, max_length=32, pattern=r"^[A-Z2-7]+$")]


class ShareRevokeRequest(_Base):
    reason: Annotated[str, Field(min_length=4, max_length=1000)]


class MapProviderConfigRequest(_Base):
    """Administrative override of the provider for one country.

    API keys never travel through this payload: they are server-side settings
    only (MAP-001). This selects *which* configured provider is used.
    """

    country_code: Annotated[str, Field(min_length=2, max_length=2)]
    provider: Literal["amap", "google_maps"]
    is_active: bool = True
