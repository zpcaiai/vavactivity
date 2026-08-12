"""Pure discovery rules (B13): city resolution, map normalization, share cards.

This module deliberately contains no database, network, settings or clock
access so that every rule below is unit-testable without a real stack. The
service layer owns transactions and I/O; this layer owns decisions.

Requirement coverage:

* GEO-001 manual city preference beats IP; IP is a *suggestion* only, never a
  persisted precise location; an empty local result falls back to national
  results and the caller is told *why*.
* MAP-001 a provider-agnostic geocoding contract. The domain model carries only
  normalized fields, a provider is chosen by event country behind a flag, and a
  geocoding failure preserves the manually entered address.
* SHARE-001 deterministic share cards, signed short links and QR targets. An
  unpublished event is never shareable, and the QR always resolves to the
  canonical authorized event URL.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

# ---------------------------------------------------------------------------
# Shared errors
# ---------------------------------------------------------------------------


class DiscoveryRuleError(Exception):
    """Raised when a caller violates a discovery rule.

    ``code`` is a stable machine identifier surfaced to clients; ``message`` is
    an operator-facing English sentence. Member-facing copy is localized in the
    frontend from ``code``, never from ``message``.
    """

    def __init__(self, code: str, message: str, *, details: Mapping[str, object] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, object] = dict(details or {})


def _canonical_json(value: object) -> str:
    """Stable JSON used for fingerprints and signatures.

    Sorted keys and no incidental whitespace, so the same logical payload always
    produces the same bytes regardless of dictionary insertion order.
    """

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# ---------------------------------------------------------------------------
# GEO-001 - city preference resolution
# ---------------------------------------------------------------------------


class LocationSource(StrEnum):
    """Where the city used for a discovery query came from."""

    #: The member picked a city. This is the only source that may be persisted
    #: as a preference (GEO-001).
    MANUAL = "manual"
    #: Derived from the request IP. Advisory only: it seeds the UI and can be
    #: used for one query, but it is never written to the member's profile.
    IP_SUGGESTION = "ip_suggestion"
    #: Nothing usable was available; the caller should show national results.
    NONE = "none"


#: Fields that would pin a member to a precise point on a map. GEO-001 forbids
#: persisting any of these when the value originated from an IP lookup, because
#: an IP-derived coordinate is both inaccurate and unnecessarily identifying.
PRECISE_LOCATION_FIELDS: frozenset[str] = frozenset(
    {
        "ip",
        "ip_address",
        "remote_addr",
        "client_ip",
        "latitude",
        "longitude",
        "lat",
        "lng",
        "lon",
        "accuracy_radius",
        "postal_code",
        "street",
        "street_address",
    }
)

#: Length of the stored IP marker. Twelve hex characters is enough to correlate
#: repeated requests for abuse analysis and far too little to reverse.
IP_MARKER_LENGTH = 12


@dataclass(frozen=True)
class ResolvedLocation:
    """The outcome of reconciling a manual preference with an IP suggestion."""

    city_code: str | None
    source: LocationSource
    #: ``True`` only when the member explicitly chose the city. A suggestion is
    #: never treated as a confirmed preference.
    is_confirmed: bool
    #: The city the IP hinted at, surfaced so the UI can offer "switch to X?".
    suggested_city_code: str | None
    #: Stable machine code explaining the decision, for the response envelope.
    reason_code: str


def normalize_city_code(value: str | None) -> str | None:
    """Normalize a city code to the stored form, or ``None`` when absent.

    City codes are opaque identifiers (an administrative division code), never
    free text, so the normalization is intentionally strict: uppercase, trimmed,
    and limited to alphanumerics plus ``-`` and ``_``.
    """

    cleaned = (value or "").strip().upper()
    if not cleaned:
        return None
    if len(cleaned) > 32:
        raise DiscoveryRuleError("CITY_CODE_TOO_LONG", "A city code may not exceed 32 characters.")
    if not all(char.isalnum() or char in "-_" for char in cleaned):
        raise DiscoveryRuleError(
            "CITY_CODE_INVALID",
            "A city code may only contain letters, digits, hyphens and underscores.",
            details={"city_code": cleaned},
        )
    return cleaned


def resolve_discovery_location(
    *,
    manual_city_code: str | None,
    ip_city_code: str | None = None,
    allow_ip_suggestion: bool = True,
) -> ResolvedLocation:
    """Decide which city a discovery query runs against.

    GEO-001's ordering is absolute: a manual preference always wins, even when
    the IP says the member is somewhere else today. That protects the common
    Chinese case of browsing events in a home city while travelling, and it
    stops a proxy or carrier NAT from silently rewriting what someone sees.

    When there is no manual preference the IP-derived city is used for *this*
    query only and reported as a suggestion, so the caller can offer to confirm
    it. ``allow_ip_suggestion=False`` (the flag is off, or the member opted out
    of IP hinting) collapses to "no city" rather than to a silent guess.
    """

    manual = normalize_city_code(manual_city_code)
    suggested = normalize_city_code(ip_city_code)
    if manual is not None:
        return ResolvedLocation(
            city_code=manual,
            source=LocationSource.MANUAL,
            is_confirmed=True,
            # Still surfaced so the UI may offer "you appear to be in X" without
            # ever acting on it by itself.
            suggested_city_code=suggested if suggested != manual else None,
            reason_code="MANUAL_PREFERENCE",
        )
    if suggested is not None and allow_ip_suggestion:
        return ResolvedLocation(
            city_code=suggested,
            source=LocationSource.IP_SUGGESTION,
            is_confirmed=False,
            suggested_city_code=suggested,
            reason_code="IP_SUGGESTION_UNCONFIRMED",
        )
    return ResolvedLocation(
        city_code=None,
        source=LocationSource.NONE,
        is_confirmed=False,
        suggested_city_code=None,
        reason_code="NO_CITY_AVAILABLE",
    )


def ensure_preference_is_persistable(resolved: ResolvedLocation) -> str:
    """Guard the write path: only a confirmed manual choice may be stored.

    Persisting an IP-derived city would turn a guess into a durable statement
    about where a member lives, which GEO-001 explicitly rules out.
    """

    if resolved.source is not LocationSource.MANUAL or not resolved.is_confirmed:
        raise DiscoveryRuleError(
            "LOCATION_NOT_PERSISTABLE",
            "Only a manually confirmed city preference may be persisted.",
            details={"source": resolved.source.value},
        )
    if resolved.city_code is None:  # pragma: no cover - defensive
        raise DiscoveryRuleError(
            "LOCATION_NOT_PERSISTABLE", "A persistable preference must carry a city code."
        )
    return resolved.city_code


def coarse_ip_marker(ip_address: str | None, *, salt: str) -> str | None:
    """Return a salted, truncated marker for an IP - never the IP itself.

    The marker exists so repeated requests from one network can be correlated
    for rate limiting and abuse review. It is a one-way digest of a salted
    value, truncated to :data:`IP_MARKER_LENGTH`, so it cannot be reversed into
    an address and cannot be joined against another system's IP logs.
    """

    if not ip_address or not ip_address.strip():
        return None
    if not salt:
        raise DiscoveryRuleError(
            "IP_MARKER_SALT_REQUIRED",
            "A salt is required before an IP marker can be derived.",
        )
    digest = hashlib.sha256()
    digest.update(salt.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(ip_address.strip().encode("utf-8"))
    return digest.hexdigest()[:IP_MARKER_LENGTH]


def build_ip_hint_record(
    *, ip_address: str | None, city_code: str | None, salt: str
) -> dict[str, str | None]:
    """Build the *only* shape an IP-derived hint may take in storage.

    A coarse city code plus an opaque marker. No coordinates, no postal code, no
    address, and no raw IP: the record is deliberately too thin to locate anyone
    (GEO-001).
    """

    return {
        "city_code": normalize_city_code(city_code),
        "ip_marker": coarse_ip_marker(ip_address, salt=salt),
    }


def reject_precise_location_fields(payload: Mapping[str, object]) -> None:
    """Fail loudly if a caller tries to persist a precise IP-derived location.

    This is a belt-and-braces check on the service layer: the shape produced by
    :func:`build_ip_hint_record` is already safe, so anything richer reaching
    the write path is a bug rather than a request to honour.
    """

    offending = sorted(key for key in payload if key.lower() in PRECISE_LOCATION_FIELDS)
    if offending:
        raise DiscoveryRuleError(
            "IP_LOCATION_TOO_PRECISE",
            "IP-derived location data may not include precise or identifying fields.",
            details={"fields": offending},
        )


# ---------------------------------------------------------------------------
# GEO-001 - national fallback with an explained reason
# ---------------------------------------------------------------------------


class ResultScope(StrEnum):
    LOCAL = "local"
    NATIONAL = "national"


class FallbackReason(StrEnum):
    """Why a query returned national results instead of local ones.

    GEO-001 requires the response to *say* why, so a member never wonders if
    their city filter silently broke.
    """

    NOT_APPLIED = "not_applied"
    NO_CITY_RESOLVED = "no_city_resolved"
    LOCAL_RESULTS_EMPTY = "local_results_empty"
    LOCAL_BELOW_MINIMUM = "local_below_minimum"


@dataclass(frozen=True)
class ScopePlan:
    scope: ResultScope
    fallback_applied: bool
    fallback_reason: FallbackReason
    city_code: str | None
    local_count: int


DEFAULT_MINIMUM_LOCAL_RESULTS = 1


def plan_result_scope(
    *,
    resolved: ResolvedLocation,
    local_count: int,
    minimum_local_results: int = DEFAULT_MINIMUM_LOCAL_RESULTS,
) -> ScopePlan:
    """Decide whether to serve local or national results, and record why.

    An empty city (or a city with too few live events) must not produce an empty
    page: the caller falls back to national results and carries the reason code
    back to the client so the UI can explain itself.
    """

    if minimum_local_results < 1:
        raise DiscoveryRuleError(
            "MINIMUM_LOCAL_RESULTS_INVALID", "minimum_local_results must be at least 1."
        )
    if local_count < 0:
        raise DiscoveryRuleError("LOCAL_COUNT_NEGATIVE", "local_count cannot be negative.")
    if resolved.city_code is None:
        return ScopePlan(
            scope=ResultScope.NATIONAL,
            fallback_applied=True,
            fallback_reason=FallbackReason.NO_CITY_RESOLVED,
            city_code=None,
            local_count=0,
        )
    if local_count == 0:
        return ScopePlan(
            scope=ResultScope.NATIONAL,
            fallback_applied=True,
            fallback_reason=FallbackReason.LOCAL_RESULTS_EMPTY,
            city_code=resolved.city_code,
            local_count=0,
        )
    if local_count < minimum_local_results:
        return ScopePlan(
            scope=ResultScope.NATIONAL,
            fallback_applied=True,
            fallback_reason=FallbackReason.LOCAL_BELOW_MINIMUM,
            city_code=resolved.city_code,
            local_count=local_count,
        )
    return ScopePlan(
        scope=ResultScope.LOCAL,
        fallback_applied=False,
        fallback_reason=FallbackReason.NOT_APPLIED,
        city_code=resolved.city_code,
        local_count=local_count,
    )


# ---------------------------------------------------------------------------
# MAP-001 - provider contract and normalized place model
# ---------------------------------------------------------------------------


class MapProviderCode(StrEnum):
    AMAP = "amap"
    GOOGLE_MAPS = "google_maps"


#: Country codes served by Amap. Mainland China only: Hong Kong, Macau and
#: Taiwan are addressed by Google Maps because Amap coverage there is partial.
AMAP_COUNTRY_CODES: frozenset[str] = frozenset({"CN"})


@dataclass(frozen=True)
class NormalizedPlace:
    """The *only* place shape the rest of the platform sees.

    Provider payloads differ wildly (``adcode`` vs ``address_components``,
    ``"lng,lat"`` strings vs nested objects). Normalizing at the boundary is
    what stops a provider swap from rippling through the domain (MAP-001).
    """

    formatted_address: str
    country_code: str
    region_code: str | None
    city_code: str | None
    latitude: float | None
    longitude: float | None
    provider: str
    provider_place_ref: str | None

    def as_payload(self) -> dict[str, object]:
        return {
            "formatted_address": self.formatted_address,
            "country_code": self.country_code,
            "region_code": self.region_code,
            "city_code": self.city_code,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "provider": self.provider,
            "provider_place_ref": self.provider_place_ref,
        }


#: The closed set of keys a normalized place may carry. Anything else is a leak.
NORMALIZED_PLACE_FIELDS: frozenset[str] = frozenset(
    {
        "formatted_address",
        "country_code",
        "region_code",
        "city_code",
        "latitude",
        "longitude",
        "provider",
        "provider_place_ref",
    }
)

#: Config keys that must never travel in a payload. API keys are server-side
#: configuration; a normalized place is returned to browsers (MAP-001).
SECRET_FIELD_MARKERS: frozenset[str] = frozenset({"key", "api_key", "secret", "token", "signature"})


def select_map_provider(
    country_code: str | None,
    *,
    amap_enabled: bool,
    google_enabled: bool,
    default_country_code: str = "CN",
) -> MapProviderCode:
    """Pick the map provider for an event by its country, behind feature flags.

    Both flags exist so a provider outage is a config change rather than a
    deploy. If the country's preferred provider is disabled the other one is
    used; if neither is enabled, geocoding is unavailable and the caller must
    fall back to the manually entered address rather than blank the venue.
    """

    country = (country_code or default_country_code or "").strip().upper()
    preferred = (
        MapProviderCode.AMAP if country in AMAP_COUNTRY_CODES else MapProviderCode.GOOGLE_MAPS
    )
    enabled = {
        MapProviderCode.AMAP: amap_enabled,
        MapProviderCode.GOOGLE_MAPS: google_enabled,
    }
    if enabled[preferred]:
        return preferred
    alternative = (
        MapProviderCode.GOOGLE_MAPS
        if preferred is MapProviderCode.AMAP
        else MapProviderCode.AMAP
    )
    if enabled[alternative]:
        return alternative
    raise DiscoveryRuleError(
        "MAP_PROVIDER_UNAVAILABLE",
        "No map provider is enabled for this country.",
        details={"country_code": country},
    )


def _coordinate(value: object, *, label: str, low: float, high: float) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise DiscoveryRuleError(
            "GEOCODE_COORDINATE_INVALID", f"{label} is not a number."
        ) from exc
    if not low <= number <= high:
        raise DiscoveryRuleError(
            "GEOCODE_COORDINATE_OUT_OF_RANGE",
            f"{label} must be between {low} and {high}.",
            details={label: number},
        )
    return number


def _normalize_amap(raw: Mapping[str, object]) -> NormalizedPlace:
    """Map an Amap geocode result onto :class:`NormalizedPlace`.

    Amap returns ``location`` as a single ``"lng,lat"`` string and encodes the
    administrative division in ``adcode``. Neither shape escapes this function.
    """

    location = str(raw.get("location") or "").strip()
    longitude: object = None
    latitude: object = None
    if location:
        parts = location.split(",")
        if len(parts) != 2:
            raise DiscoveryRuleError(
                "GEOCODE_PAYLOAD_INVALID", "Amap location must be a 'lng,lat' pair."
            )
        longitude, latitude = parts[0], parts[1]
    return NormalizedPlace(
        formatted_address=str(raw.get("formatted_address") or "").strip(),
        country_code=str(raw.get("country_code") or "CN").strip().upper(),
        region_code=(str(raw.get("province_adcode")).strip() or None)
        if raw.get("province_adcode")
        else None,
        city_code=normalize_city_code(str(raw.get("adcode") or "") or None),
        latitude=_coordinate(latitude, label="latitude", low=-90.0, high=90.0),
        longitude=_coordinate(longitude, label="longitude", low=-180.0, high=180.0),
        provider=MapProviderCode.AMAP.value,
        provider_place_ref=(str(raw.get("id")).strip() or None) if raw.get("id") else None,
    )


def _normalize_google(raw: Mapping[str, object]) -> NormalizedPlace:
    """Map a Google Maps geocode result onto :class:`NormalizedPlace`."""

    geometry = raw.get("geometry") or {}
    location = geometry.get("location", {}) if isinstance(geometry, Mapping) else {}
    components = raw.get("address_components") or []
    country_code = ""
    region_code: str | None = None
    city_code: str | None = None
    if isinstance(components, Sequence):
        for component in components:
            if not isinstance(component, Mapping):
                continue
            types = component.get("types") or ()
            short = str(component.get("short_name") or "").strip()
            if "country" in types:
                country_code = short.upper()
            elif "administrative_area_level_1" in types and region_code is None:
                region_code = short or None
            elif "locality" in types and city_code is None:
                city_code = short or None
    return NormalizedPlace(
        formatted_address=str(raw.get("formatted_address") or "").strip(),
        country_code=country_code or "",
        region_code=region_code,
        city_code=normalize_city_code(city_code),
        latitude=_coordinate(
            location.get("lat") if isinstance(location, Mapping) else None,
            label="latitude",
            low=-90.0,
            high=90.0,
        ),
        longitude=_coordinate(
            location.get("lng") if isinstance(location, Mapping) else None,
            label="longitude",
            low=-180.0,
            high=180.0,
        ),
        provider=MapProviderCode.GOOGLE_MAPS.value,
        provider_place_ref=(str(raw.get("place_id")).strip() or None)
        if raw.get("place_id")
        else None,
    )


def normalize_geocode_result(
    provider: MapProviderCode | str, raw: Mapping[str, object]
) -> NormalizedPlace:
    """Normalize any provider payload into the single domain shape.

    Raises rather than guessing when the payload lacks an address: a place with
    no address is not useful, and silently inventing one would be worse than
    reporting a geocode failure and keeping what the operator typed.
    """

    try:
        code = MapProviderCode(provider)
    except ValueError as exc:
        raise DiscoveryRuleError(
            "MAP_PROVIDER_UNKNOWN", f"Unknown map provider: {provider}"
        ) from exc
    place = _normalize_amap(raw) if code is MapProviderCode.AMAP else _normalize_google(raw)
    if not place.formatted_address:
        raise DiscoveryRuleError(
            "GEOCODE_ADDRESS_MISSING",
            "The provider returned no formatted address.",
            details={"provider": code.value},
        )
    return place


def assert_no_provider_leakage(payload: Mapping[str, object]) -> None:
    """Fail if a place payload carries provider-specific or secret fields.

    Called on the way out of the service layer so a future provider integration
    cannot quietly widen the contract (MAP-001).
    """

    extra = sorted(set(payload) - NORMALIZED_PLACE_FIELDS)
    if extra:
        raise DiscoveryRuleError(
            "PLACE_PAYLOAD_LEAK",
            "A place payload may only contain the normalized fields.",
            details={"fields": extra},
        )
    secrets = sorted(
        key
        for key in payload
        if any(marker in key.lower() for marker in SECRET_FIELD_MARKERS)
    )
    if secrets:  # pragma: no cover - unreachable while the field set is closed
        raise DiscoveryRuleError(
            "PLACE_PAYLOAD_SECRET",
            "A place payload may never contain credentials.",
            details={"fields": secrets},
        )


class GeocodeStatus(StrEnum):
    RESOLVED = "resolved"
    #: The provider was called and could not resolve the address. The manually
    #: entered address stays exactly as typed.
    FAILED = "failed"
    #: Geocoding was not attempted (flag off, no provider, or manual override).
    SKIPPED = "skipped"


@dataclass(frozen=True)
class VenueLocation:
    """What the activities module stores for an event venue."""

    manual_address: str
    geocode_status: GeocodeStatus
    place: NormalizedPlace | None
    failure_code: str | None

    @property
    def display_address(self) -> str:
        """The address shown to members.

        The provider's formatted address is preferred when geocoding worked,
        because it is canonical; otherwise the operator's own text is shown.
        Either way this is never empty when the operator typed something.
        """

        if self.place is not None and self.place.formatted_address:
            return self.place.formatted_address
        return self.manual_address


def resolve_venue_location(
    *,
    manual_address: str,
    place: NormalizedPlace | None = None,
    failure_code: str | None = None,
    attempted: bool = True,
) -> VenueLocation:
    """Combine an operator-entered address with a geocoding outcome.

    MAP-001's key rule: **a geocoding failure preserves the manual address**.
    Blanking a venue because a third-party API was down would delete real
    operator work and leave members with an event they cannot find.
    """

    address = (manual_address or "").strip()
    if not address and place is None:
        raise DiscoveryRuleError(
            "VENUE_ADDRESS_REQUIRED",
            "A venue requires a manually entered address.",
        )
    if place is not None:
        return VenueLocation(
            manual_address=address,
            geocode_status=GeocodeStatus.RESOLVED,
            place=place,
            failure_code=None,
        )
    return VenueLocation(
        manual_address=address,
        geocode_status=GeocodeStatus.FAILED if attempted else GeocodeStatus.SKIPPED,
        place=None,
        failure_code=(failure_code or "GEOCODE_UNAVAILABLE") if attempted else None,
    )


def display_link(place: NormalizedPlace | None, *, fallback_query: str) -> str | None:
    """Build a provider deep link for "open in maps".

    Returns ``None`` when there is nothing to link to, which is a valid state:
    the UI then shows the address as plain text rather than a broken link. No
    API key ever appears in a display link; these are public map URLs.
    """

    query = (fallback_query or "").strip()
    if place is None:
        return None
    if place.latitude is not None and place.longitude is not None:
        if place.provider == MapProviderCode.AMAP.value:
            return (
                "https://uri.amap.com/marker"
                f"?position={place.longitude},{place.latitude}"
                f"&name={place.formatted_address or query}"
            )
        return (
            "https://www.google.com/maps/search/?api=1"
            f"&query={place.latitude},{place.longitude}"
        )
    if not (place.formatted_address or query):
        return None
    if place.provider == MapProviderCode.AMAP.value:
        return f"https://uri.amap.com/search?keyword={place.formatted_address or query}"
    return f"https://www.google.com/maps/search/?api=1&query={place.formatted_address or query}"


# ---------------------------------------------------------------------------
# SHARE-001 - shareability, deterministic cards, signed links, QR
# ---------------------------------------------------------------------------


class EventPublicationStatus(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    PUBLISHED = "published"
    UNPUBLISHED = "unpublished"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class EventVisibility(StrEnum):
    PUBLIC = "public"
    #: Reachable only with a link; still not publicly shareable as a card.
    UNLISTED = "unlisted"
    PRIVATE = "private"


#: The only publication status that permits a public share (SHARE-001).
SHAREABLE_PUBLICATION_STATUSES: frozenset[EventPublicationStatus] = frozenset(
    {EventPublicationStatus.PUBLISHED}
)

#: The only visibility that permits a public share. ``unlisted`` deliberately
#: does not: a share card is an act of broadcasting, not of link-passing.
SHAREABLE_VISIBILITIES: frozenset[EventVisibility] = frozenset({EventVisibility.PUBLIC})


def is_event_shareable(
    *, publication_status: str, visibility: str, sharing_enabled: bool = True
) -> bool:
    """Cheap predicate mirroring :func:`ensure_event_shareable`."""

    try:
        ensure_event_shareable(
            publication_status=publication_status,
            visibility=visibility,
            sharing_enabled=sharing_enabled,
        )
    except DiscoveryRuleError:
        return False
    return True


def ensure_event_shareable(
    *, publication_status: str, visibility: str, sharing_enabled: bool = True
) -> None:
    """Reject share creation for anything that is not publicly published.

    A draft is a work in progress; an unpublished or cancelled event is one the
    organiser has taken down. Letting either escape via a share card would leak
    unreleased pricing and venue details to the open internet, so this fails
    closed on any unknown status (SHARE-001).
    """

    if not sharing_enabled:
        raise DiscoveryRuleError(
            "SHARE_DISABLED", "Event sharing is not enabled.", details={"reason": "feature_flag"}
        )
    try:
        status = EventPublicationStatus(publication_status)
    except ValueError as exc:
        raise DiscoveryRuleError(
            "SHARE_STATUS_UNKNOWN",
            "Unknown event publication status; refusing to share.",
            details={"publication_status": publication_status},
        ) from exc
    try:
        scope = EventVisibility(visibility)
    except ValueError as exc:
        raise DiscoveryRuleError(
            "SHARE_VISIBILITY_UNKNOWN",
            "Unknown event visibility; refusing to share.",
            details={"visibility": visibility},
        ) from exc
    if status not in SHAREABLE_PUBLICATION_STATUSES:
        raise DiscoveryRuleError(
            "SHARE_EVENT_NOT_PUBLISHED",
            "Only a published event can be shared publicly.",
            details={"publication_status": status.value},
        )
    if scope not in SHAREABLE_VISIBILITIES:
        raise DiscoveryRuleError(
            "SHARE_EVENT_NOT_PUBLIC",
            "Only a publicly visible event can be shared publicly.",
            details={"visibility": scope.value},
        )


#: Used when an event has no cover image. A deterministic placeholder keeps the
#: card snapshot-testable instead of producing a card with a null image.
DEFAULT_COVER_PLACEHOLDER = "placeholder:event-cover-default"


@dataclass(frozen=True)
class CoverImage:
    url: str
    is_fallback: bool


def resolve_cover_image(
    cover_image_url: str | None, *, placeholder: str = DEFAULT_COVER_PLACEHOLDER
) -> CoverImage:
    """Choose the card's image, degrading gracefully when none exists.

    SHARE-001 requires a graceful fallback rather than a broken card: a missing
    cover is common for freshly created events and must not block sharing.
    """

    url = (cover_image_url or "").strip()
    if url:
        return CoverImage(url=url, is_fallback=False)
    return CoverImage(url=placeholder, is_fallback=True)


@dataclass(frozen=True)
class ShareCard:
    """A deterministic, snapshot-testable share card payload."""

    event_id: UUID
    card_version: int
    title: str
    subtitle: str | None
    city_code: str | None
    starts_at: datetime
    cover_image_url: str
    cover_is_fallback: bool
    canonical_url: str

    def as_payload(self) -> dict[str, object]:
        """The exact serialized form. Key order is irrelevant: the fingerprint
        is computed over a canonical JSON encoding with sorted keys."""

        return {
            "event_id": str(self.event_id),
            "card_version": self.card_version,
            "title": self.title,
            "subtitle": self.subtitle,
            "city_code": self.city_code,
            "starts_at": self.starts_at.astimezone(UTC).isoformat(),
            "cover_image_url": self.cover_image_url,
            "cover_is_fallback": self.cover_is_fallback,
            "canonical_url": self.canonical_url,
        }

    @property
    def fingerprint(self) -> str:
        """Stable hash of the payload.

        Same event plus same version always yields the same fingerprint, which
        is what lets the service skip regenerating an image and what lets a test
        assert on a snapshot (SHARE-001).
        """

        return hashlib.sha256(_canonical_json(self.as_payload()).encode("utf-8")).hexdigest()


def canonical_event_url(base_url: str, event_id: UUID) -> str:
    """The one authorized public URL for an event.

    Every share surface - card, short link, QR - resolves here, so access
    control is enforced in exactly one place.
    """

    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise DiscoveryRuleError(
            "SHARE_BASE_URL_REQUIRED", "A public base URL is required to build a share target."
        )
    if not base.startswith("https://"):
        # http:// share links would be rewritable in transit, and a share card
        # is exactly the thing an attacker would want to repoint.
        raise DiscoveryRuleError(
            "SHARE_BASE_URL_INSECURE", "The public base URL must use HTTPS."
        )
    return f"{base}/events/{event_id}"


def build_share_card(
    *,
    event_id: UUID,
    card_version: int,
    title: str,
    starts_at: datetime,
    base_url: str,
    subtitle: str | None = None,
    city_code: str | None = None,
    cover_image_url: str | None = None,
    publication_status: str,
    visibility: str,
    sharing_enabled: bool = True,
) -> ShareCard:
    """Build the deterministic card for a published event.

    Shareability is checked *here* rather than at the router so no caller can
    reach card generation for a draft event by another route.
    """

    ensure_event_shareable(
        publication_status=publication_status,
        visibility=visibility,
        sharing_enabled=sharing_enabled,
    )
    if starts_at.tzinfo is None:
        raise DiscoveryRuleError("SHARE_NAIVE_DATETIME", "starts_at must be timezone-aware.")
    if card_version < 1:
        raise DiscoveryRuleError("SHARE_CARD_VERSION_INVALID", "card_version must be at least 1.")
    cleaned_title = (title or "").strip()
    if not cleaned_title:
        raise DiscoveryRuleError("SHARE_TITLE_REQUIRED", "A share card requires a title.")
    cover = resolve_cover_image(cover_image_url)
    return ShareCard(
        event_id=event_id,
        card_version=card_version,
        title=cleaned_title,
        subtitle=(subtitle or "").strip() or None,
        city_code=normalize_city_code(city_code),
        starts_at=starts_at,
        cover_image_url=cover.url,
        cover_is_fallback=cover.is_fallback,
        canonical_url=canonical_event_url(base_url, event_id),
    )


#: Length of the public short code. Base32 over an HMAC digest: 10 characters is
#: ~50 bits, far too large to enumerate, and still typable.
SHORT_CODE_LENGTH = 10

_SHORT_CODE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"


def short_link_code(event_id: UUID, share_version: int, *, secret: str) -> str:
    """Derive the short code deterministically from the event and version.

    Deterministic so a re-issued link for the same version is the same link
    (idempotent generation), and keyed so codes cannot be predicted from the
    event id alone.
    """

    if not secret:
        raise DiscoveryRuleError(
            "SHARE_SECRET_REQUIRED", "A signing secret is required for share links."
        )
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{event_id}:{share_version}".encode(),
        hashlib.sha256,
    ).digest()
    encoded = base64.b32encode(digest).decode("ascii").rstrip("=")
    return "".join(char for char in encoded if char in _SHORT_CODE_ALPHABET)[:SHORT_CODE_LENGTH]


def sign_share_token(payload: Mapping[str, object], *, secret: str) -> str:
    """HMAC-SHA256 over the canonical JSON form of ``payload``."""

    if not secret:
        raise DiscoveryRuleError(
            "SHARE_SECRET_REQUIRED", "A signing secret is required for share links."
        )
    return hmac.new(
        secret.encode("utf-8"), _canonical_json(payload).encode("utf-8"), hashlib.sha256
    ).hexdigest()


def verify_share_token(
    payload: Mapping[str, object], signature: str, *, secret: str
) -> bool:
    """Constant-time signature check. Never short-circuits on the first byte."""

    return hmac.compare_digest(sign_share_token(payload, secret=secret), signature or "")


@dataclass(frozen=True)
class ShareLink:
    short_code: str
    signature: str
    canonical_url: str
    expires_at: datetime | None


DEFAULT_SHARE_LINK_TTL_HOURS = 720


def issue_share_link(
    *,
    event_id: UUID,
    share_version: int,
    base_url: str,
    secret: str,
    issued_at: datetime,
    ttl_hours: int | None = DEFAULT_SHARE_LINK_TTL_HOURS,
    publication_status: str,
    visibility: str,
    sharing_enabled: bool = True,
) -> ShareLink:
    """Mint a signed short link for a published event.

    ``ttl_hours=None`` means "no expiry", which is valid for an evergreen event
    page; any positive value produces an expiry the resolver enforces.
    """

    ensure_event_shareable(
        publication_status=publication_status,
        visibility=visibility,
        sharing_enabled=sharing_enabled,
    )
    if issued_at.tzinfo is None:
        raise DiscoveryRuleError("SHARE_NAIVE_DATETIME", "issued_at must be timezone-aware.")
    if ttl_hours is not None and ttl_hours <= 0:
        raise DiscoveryRuleError("SHARE_TTL_INVALID", "ttl_hours must be positive when supplied.")
    code = short_link_code(event_id, share_version, secret=secret)
    expires_at = issued_at + timedelta(hours=ttl_hours) if ttl_hours is not None else None
    payload = {
        "event_id": str(event_id),
        "share_version": share_version,
        "short_code": code,
        "expires_at": expires_at.astimezone(UTC).isoformat() if expires_at else None,
    }
    return ShareLink(
        short_code=code,
        signature=sign_share_token(payload, secret=secret),
        canonical_url=canonical_event_url(base_url, event_id),
        expires_at=expires_at,
    )


def resolve_share_link(
    *,
    link: ShareLink,
    event_id: UUID,
    share_version: int,
    secret: str,
    now: datetime,
    publication_status: str,
    visibility: str,
    sharing_enabled: bool = True,
) -> str:
    """Validate a short link and return the canonical URL to redirect to.

    Publication is re-checked at *resolve* time, not only at issue time: an
    event that is unpublished after a link was shared must stop resolving. That
    is the difference between a share link and a permanent leak (SHARE-001).
    """

    if now.tzinfo is None:
        raise DiscoveryRuleError("SHARE_NAIVE_DATETIME", "now must be timezone-aware.")
    payload = {
        "event_id": str(event_id),
        "share_version": share_version,
        "short_code": link.short_code,
        "expires_at": link.expires_at.astimezone(UTC).isoformat() if link.expires_at else None,
    }
    if not verify_share_token(payload, link.signature, secret=secret):
        raise DiscoveryRuleError(
            "SHARE_LINK_SIGNATURE_INVALID", "The share link signature does not match."
        )
    if link.expires_at is not None and now > link.expires_at:
        raise DiscoveryRuleError(
            "SHARE_LINK_EXPIRED",
            "This share link has expired.",
            details={"expires_at": link.expires_at.astimezone(UTC).isoformat()},
        )
    ensure_event_shareable(
        publication_status=publication_status,
        visibility=visibility,
        sharing_enabled=sharing_enabled,
    )
    return link.canonical_url


def build_qr_target(
    *, canonical_url: str, short_code: str | None = None, campaign: str | None = None
) -> str:
    """Return the string a QR image encodes.

    The QR always points at the canonical authorized event URL - never at an
    intermediate redirector - so scanning it lands on the page that enforces
    access control. Attribution travels as query parameters, which cannot change
    which resource is fetched (SHARE-001).
    """

    if not canonical_url.startswith("https://"):
        raise DiscoveryRuleError(
            "QR_TARGET_INSECURE", "A QR target must be an HTTPS canonical event URL."
        )
    if "/events/" not in canonical_url:
        raise DiscoveryRuleError(
            "QR_TARGET_NOT_CANONICAL",
            "A QR target must be the canonical event URL.",
            details={"target": canonical_url},
        )
    params: list[str] = []
    if short_code:
        params.append(f"s={short_code}")
    if campaign:
        params.append(f"c={campaign}")
    return canonical_url + ("?" + "&".join(params) if params else "")


def assert_qr_target_is_canonical(target: str, *, canonical_url: str) -> None:
    """Guard used by tests and by the service before persisting a QR asset."""

    if not target.startswith(canonical_url):
        raise DiscoveryRuleError(
            "QR_TARGET_NOT_CANONICAL",
            "The QR target does not resolve to the canonical event URL.",
            details={"target": target, "canonical_url": canonical_url},
        )
