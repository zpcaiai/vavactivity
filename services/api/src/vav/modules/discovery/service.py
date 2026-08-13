"""Transactional discovery service (B13: GEO-001 / MAP-001 / SHARE-001).

Design notes:

* All business rules live in :mod:`vav.modules.discovery.domain` so they are
  testable without a database; this layer only loads state, calls domain and
  persists.
* Nothing precise derived from an IP address is ever written. The only shape
  that reaches storage is the coarse ``{city_code, ip_marker}`` record produced
  by the domain (GEO-001).
* Map provider credentials are read from settings inside this module and never
  returned to a caller. The :class:`MapProvider` contract is a *port*: the HTTP
  transport is injected so this module stays unit-testable and so a provider
  outage degrades to "keep the manually entered address" rather than an error.
* Share links are re-validated against the activity's publication status on
  every resolve, so unpublishing an event kills links that are already in the
  wild.
"""

# ruff: noqa: E501

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.discovery.domain import (
    DiscoveryRuleError,
    GeocodeStatus,
    LocationSource,
    MapProviderCode,
    NormalizedPlace,
    ResolvedLocation,
    VenueLocation,
    assert_no_provider_leakage,
    assert_qr_target_is_canonical,
    build_ip_hint_record,
    build_qr_target,
    build_share_card,
    canonical_event_url,
    display_link,
    ensure_event_shareable,
    ensure_preference_is_persistable,
    issue_share_link,
    normalize_city_code,
    normalize_geocode_result,
    plan_result_scope,
    reject_precise_location_fields,
    resolve_discovery_location,
    resolve_venue_location,
    select_map_provider,
    short_link_code,
    verify_share_token,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _secret_value(secret: object) -> str:
    """Unwrap a pydantic ``SecretStr`` into the plain string the domain signs with.

    The domain layer takes ``secret: str`` and guards on falsiness, so passing
    the SecretStr object straight through would silently defeat that guard —
    a SecretStr is always truthy — and then fail on ``.encode()``.
    """

    if secret is None:
        return ""
    getter = getattr(secret, "get_secret_value", None)
    return str(getter() if callable(getter) else secret)


def _fail(error: DiscoveryRuleError, status_code: int = 422) -> VavError:
    """Translate a pure-domain violation into the platform error envelope.

    ``VavError.details`` is a list in this codebase, so the rule's structured
    context is wrapped rather than passed through as a mapping.
    """

    return VavError(
        error.code,
        error.message,
        status_code=status_code,
        details=[error.details] if error.details else None,
    )


def geo_enabled() -> None:
    if not get_settings().discovery_geo_enabled:
        raise VavError(
            "DISCOVERY_GEO_DISABLED", "City-scoped discovery is not enabled.", status_code=503
        )


def sharing_enabled() -> bool:
    return bool(get_settings().event_sharing_enabled)


def require_sharing_enabled() -> None:
    if not sharing_enabled():
        raise VavError("EVENT_SHARING_DISABLED", "Event sharing is not enabled.", status_code=503)


async def _publish(
    session: AsyncSession,
    topic: str,
    aggregate_type: str,
    aggregate_id: UUID,
    payload: dict[str, Any],
) -> None:
    await session.execute(
        text(
            "INSERT INTO outbox_events (topic,aggregate_type,aggregate_id,payload) "
            "VALUES (:topic,:aggregate_type,:id,CAST(:payload AS jsonb))"
        ),
        {
            "topic": topic,
            "aggregate_type": aggregate_type,
            "id": str(aggregate_id),
            "payload": _json(payload),
        },
    )


async def _audit(
    session: AsyncSession,
    *,
    subject_type: str,
    subject_id: UUID | None,
    actor_id: UUID | None,
    actor_kind: str,
    action: str,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO discovery_audits "
            "(subject_type,subject_id,actor_id,actor_kind,action,reason,metadata) "
            "VALUES (:subject_type,:subject_id,:actor_id,:actor_kind,:action,:reason,CAST(:metadata AS jsonb))"
        ),
        {
            "subject_type": subject_type,
            "subject_id": str(subject_id) if subject_id else None,
            "actor_id": str(actor_id) if actor_id else None,
            "actor_kind": actor_kind,
            "action": action,
            "reason": reason,
            "metadata": _json(metadata or {}),
        },
    )


# ---------------------------------------------------------------------------
# GEO-001 city preference
# ---------------------------------------------------------------------------


async def get_city_preference(session: AsyncSession, user_id: UUID) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT city_code,allow_ip_suggestion,confirmed_at FROM member_city_preferences "
                    "WHERE user_id=:user_id"
                ),
                {"user_id": str(user_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        # No row is a real answer: the member has never chosen a city, so IP may
        # suggest one but nothing is pinned.
        return {"city_code": None, "allow_ip_suggestion": True, "confirmed_at": None}
    return dict(row)


async def set_city_preference(
    session: AsyncSession, *, user_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Persist (or clear) the member's manual city preference.

    Only a manually confirmed choice reaches this table - the domain guard
    refuses anything sourced from an IP lookup (GEO-001).
    """

    geo_enabled()
    city_code = payload.get("city_code")
    allow_ip = bool(payload.get("allow_ip_suggestion", True))
    if city_code is None:
        await session.execute(
            text(
                "INSERT INTO member_city_preferences (user_id,city_code,allow_ip_suggestion,confirmed_at) "
                "VALUES (:user_id,NULL,:allow_ip,NULL) "
                "ON CONFLICT (user_id) DO UPDATE SET city_code=NULL,confirmed_at=NULL,"
                "allow_ip_suggestion=EXCLUDED.allow_ip_suggestion,updated_at=now()"
            ),
            {"user_id": str(user_id), "allow_ip": allow_ip},
        )
        await session.commit()
        return await get_city_preference(session, user_id)

    try:
        resolved = resolve_discovery_location(manual_city_code=city_code)
        normalized = ensure_preference_is_persistable(resolved)
    except DiscoveryRuleError as error:
        raise _fail(error) from error
    await session.execute(
        text(
            "INSERT INTO member_city_preferences (user_id,city_code,allow_ip_suggestion,confirmed_at) "
            "VALUES (:user_id,:city_code,:allow_ip,now()) "
            "ON CONFLICT (user_id) DO UPDATE SET city_code=EXCLUDED.city_code,"
            "allow_ip_suggestion=EXCLUDED.allow_ip_suggestion,confirmed_at=now(),updated_at=now()"
        ),
        {"user_id": str(user_id), "city_code": normalized, "allow_ip": allow_ip},
    )
    await session.commit()
    return await get_city_preference(session, user_id)


async def record_ip_hint(
    session: AsyncSession, *, user_id: UUID | None, ip_address: str | None, city_code: str | None
) -> None:
    """Store the *only* permitted IP-derived record: coarse city plus marker.

    Written for abuse analysis, not for personalization. The domain builds the
    record and a second guard rejects any payload that grew a precise field.
    """

    settings = get_settings()
    if not settings.discovery_ip_suggestion_enabled:
        return
    try:
        record = build_ip_hint_record(
            ip_address=ip_address,
            city_code=city_code,
            salt=_secret_value(settings.discovery_ip_marker_salt),
        )
        reject_precise_location_fields(record)
    except DiscoveryRuleError as error:
        raise _fail(error) from error
    if record["ip_marker"] is None and record["city_code"] is None:
        return
    await session.execute(
        text(
            "INSERT INTO discovery_ip_hints (user_id,city_code,ip_marker) "
            "VALUES (:user_id,:city_code,:ip_marker)"
        ),
        {
            "user_id": str(user_id) if user_id else None,
            "city_code": record["city_code"],
            "ip_marker": record["ip_marker"],
        },
    )


async def resolve_location(
    session: AsyncSession,
    *,
    user_id: UUID | None,
    ip_city_code: str | None = None,
    override_city_code: str | None = None,
) -> ResolvedLocation:
    """Reconcile the stored preference, a per-request override and the IP hint.

    A per-request override behaves exactly like a manual preference for this
    call and is *not* written back: switching city to browse once should not
    silently rewrite where the member says they live.
    """

    settings = get_settings()
    stored: dict[str, Any] = {"city_code": None, "allow_ip_suggestion": True}
    if user_id is not None:
        stored = await get_city_preference(session, user_id)
    manual = override_city_code or stored.get("city_code")
    try:
        return resolve_discovery_location(
            manual_city_code=manual,
            ip_city_code=ip_city_code,
            allow_ip_suggestion=bool(stored.get("allow_ip_suggestion", True))
            and settings.discovery_ip_suggestion_enabled,
        )
    except DiscoveryRuleError as error:
        raise _fail(error) from error


async def discovery_feed(
    session: AsyncSession,
    *,
    user_id: UUID | None,
    ip_city_code: str | None = None,
    override_city_code: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """City-scoped event feed with an explained national fallback.

    The local count is measured first, the domain decides the scope, and only
    then are rows fetched. The response always carries ``fallback_reason`` so
    the client can say why it is showing national results (GEO-001).
    """

    geo_enabled()
    resolved = await resolve_location(
        session,
        user_id=user_id,
        ip_city_code=ip_city_code,
        override_city_code=override_city_code,
    )
    local_count = 0
    if resolved.city_code is not None:
        local_count = int(
            await session.scalar(
                text(
                    "SELECT count(*) FROM activities a "
                    "LEFT JOIN activity_venue_locations v ON v.activity_id=a.id "
                    "WHERE a.status='published' AND a.visibility='public' "
                    "AND v.city_code=:city_code"
                ),
                {"city_code": resolved.city_code},
            )
            or 0
        )
    try:
        plan = plan_result_scope(
            resolved=resolved,
            local_count=local_count,
            minimum_local_results=get_settings().discovery_minimum_local_results,
        )
    except DiscoveryRuleError as error:
        raise _fail(error) from error

    # The domain owns the decision; the query merely reflects it.
    clause = "" if plan.fallback_applied else " AND v.city_code=:city_code"
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if clause:
        params["city_code"] = plan.city_code
    rows = (
        (
            await session.execute(
                text(
                    "SELECT a.id,loc.title,a.starts_at,"
                    "loc.cover_media_id::text AS cover_image_url,v.city_code,"
                    "COALESCE(v.formatted_address, v.manual_address) AS display_address "
                    "FROM activities a "
                    "LEFT JOIN activity_localizations loc ON loc.activity_id=a.id AND loc.locale=a.default_locale "
                    "LEFT JOIN activity_venue_locations v ON v.activity_id=a.id "
                    "WHERE a.status='published' AND a.visibility='public'"
                    + clause
                    + " ORDER BY a.starts_at ASC, a.id LIMIT :limit OFFSET :offset"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    return {
        "scope": plan.scope.value,
        "city_code": plan.city_code,
        "city_source": resolved.source.value,
        "city_is_confirmed": resolved.is_confirmed,
        "suggested_city_code": resolved.suggested_city_code,
        "fallback_applied": plan.fallback_applied,
        # The whole point of GEO-001: the client is told *why* it fell back.
        "fallback_reason": plan.fallback_reason.value,
        "local_count": plan.local_count,
        "items": [
            {key: str(value) if isinstance(value, UUID) else value for key, value in row.items()}
            for row in rows
        ],
    }


# ---------------------------------------------------------------------------
# MAP-001 the provider port
# ---------------------------------------------------------------------------


class MapProviderUnavailable(Exception):
    """Raised by a provider adapter when the upstream call could not complete.

    Deliberately not a :class:`VavError`: a geocoding outage is not a request
    failure. The caller catches it and preserves the manually entered address.
    """


class MapProvider(Protocol):
    """The contract every map integration implements.

    Two methods only. Anything provider-specific stays behind them: the
    ``geocode`` return value is normalized before it leaves the adapter, and
    ``display_link`` builds a public URL that never carries an API key.
    """

    code: MapProviderCode

    async def geocode(
        self, address: str, *, city_code: str | None = None
    ) -> NormalizedPlace | None:
        """Resolve an address, or return ``None`` when the provider found nothing."""

    def display_link(self, place: NormalizedPlace | None, *, fallback_query: str) -> str | None:
        """Build an "open in maps" URL for a normalized place."""


#: Injected by infrastructure at startup. Signature:
#: ``async (provider_code, url, params) -> mapping``. Kept as a module-level
#: hook so this module has no direct HTTP dependency and stays importable in
#: tests. It is async because geocoding happens inside async request handlers —
#: a blocking call here would stall the event loop for every other request.
FetchJson = Callable[[str, str, Mapping[str, Any]], Awaitable[Mapping[str, Any]]]

_fetch_json: FetchJson | None = None


def register_geocode_fetcher(fetcher: FetchJson | None) -> None:
    """Wire the HTTP transport used by the provider adapters."""

    global _fetch_json
    _fetch_json = fetcher


async def _fetch(
    provider: MapProviderCode, url: str, params: Mapping[str, Any]
) -> Mapping[str, Any]:
    if _fetch_json is None:
        raise MapProviderUnavailable("No geocode transport is registered.")
    try:
        return await _fetch_json(provider.value, url, params)
    except MapProviderUnavailable:
        raise
    except Exception as exc:  # pragma: no cover - transport specific
        raise MapProviderUnavailable(str(exc)) from exc


class AmapProvider:
    """Amap (Gaode) adapter. Used for mainland-China events."""

    code = MapProviderCode.AMAP
    endpoint = "https://restapi.amap.com/v3/geocode/geo"

    def __init__(self, api_key: str) -> None:
        # The key lives here and nowhere else; it never enters a response body.
        self._api_key = api_key

    async def geocode(
        self, address: str, *, city_code: str | None = None
    ) -> NormalizedPlace | None:
        payload = await _fetch(
            self.code,
            self.endpoint,
            {"key": self._api_key, "address": address, "city": city_code or ""},
        )
        results = payload.get("geocodes") or []
        if not results:
            return None
        raw = dict(results[0])
        raw.setdefault("formatted_address", raw.get("formatted_address") or address)
        raw.setdefault("country_code", "CN")
        return normalize_geocode_result(self.code, raw)

    def display_link(self, place: NormalizedPlace | None, *, fallback_query: str) -> str | None:
        return display_link(place, fallback_query=fallback_query)


class GoogleMapsProvider:
    """Google Maps adapter. Used for every non-mainland-China event."""

    code = MapProviderCode.GOOGLE_MAPS
    endpoint = "https://maps.googleapis.com/maps/api/geocode/json"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def geocode(
        self, address: str, *, city_code: str | None = None
    ) -> NormalizedPlace | None:
        payload = await _fetch(self.code, self.endpoint, {"key": self._api_key, "address": address})
        results = payload.get("results") or []
        if not results:
            return None
        return normalize_geocode_result(self.code, dict(results[0]))

    def display_link(self, place: NormalizedPlace | None, *, fallback_query: str) -> str | None:
        return display_link(place, fallback_query=fallback_query)


def build_provider(country_code: str | None) -> MapProvider:
    """Choose and construct the provider for a country, behind the flags."""

    settings = get_settings()
    try:
        code = select_map_provider(
            country_code,
            amap_enabled=settings.map_amap_enabled,
            google_enabled=settings.map_google_enabled,
        )
    except DiscoveryRuleError as error:
        raise _fail(error, status_code=503) from error
    # The key is a SecretStr in configuration. Unwrap it here — and only here —
    # so it never travels as an object that could be logged by accident. A
    # provider that is enabled but has no key is a misconfiguration, not a
    # reason to call an API with `key=None`.
    secret = (
        settings.map_amap_api_key if code is MapProviderCode.AMAP else (settings.map_google_api_key)
    )
    api_key = secret.get_secret_value().strip() if secret is not None else ""
    if not api_key:
        raise VavError(
            "MAP_PROVIDER_KEY_MISSING",
            f"Map provider {code.value} is enabled but no API key is configured.",
            status_code=503,
        )
    if code is MapProviderCode.AMAP:
        return AmapProvider(api_key)
    return GoogleMapsProvider(api_key)


async def geocode_address(
    *, manual_address: str, country_code: str | None, city_code: str | None = None
) -> VenueLocation:
    """Geocode an address, preserving the operator's text on any failure.

    Every failure path - provider disabled, transport down, no result, a payload
    the normalizer rejects - produces a ``VenueLocation`` that still carries the
    manually entered address. That is MAP-001's central requirement.
    """

    try:
        provider = build_provider(country_code)
    except VavError:
        return resolve_venue_location(
            manual_address=manual_address,
            place=None,
            failure_code="GEOCODE_PROVIDER_UNAVAILABLE",
        )
    try:
        place = await provider.geocode(manual_address, city_code=city_code)
    except MapProviderUnavailable:
        return resolve_venue_location(
            manual_address=manual_address, place=None, failure_code="GEOCODE_BACKEND_UNAVAILABLE"
        )
    except DiscoveryRuleError as error:
        # A payload we cannot normalize is treated as "no result" rather than a
        # hard error, so a provider schema change never blocks event creation.
        return resolve_venue_location(
            manual_address=manual_address, place=None, failure_code=error.code
        )
    try:
        return resolve_venue_location(
            manual_address=manual_address,
            place=place,
            failure_code="GEOCODE_NO_RESULT" if place is None else None,
        )
    except DiscoveryRuleError as error:
        raise _fail(error) from error


async def geocode_preview(session: AsyncSession, *, payload: dict[str, Any]) -> dict[str, Any]:
    """Operator-facing geocode preview used by the venue editor."""

    venue = await geocode_address(
        manual_address=payload["manual_address"],
        country_code=payload.get("country_code"),
        city_code=payload.get("city_code"),
    )
    return _venue_payload(venue)


def _venue_payload(venue: VenueLocation) -> dict[str, Any]:
    place_payload = venue.place.as_payload() if venue.place else None
    if place_payload is not None:
        try:
            assert_no_provider_leakage(place_payload)
        except DiscoveryRuleError as error:  # pragma: no cover - defensive
            raise _fail(error, status_code=500) from error
    return {
        "manual_address": venue.manual_address,
        "display_address": venue.display_address,
        "geocode_status": venue.geocode_status.value,
        "failure_code": venue.failure_code,
        "place": place_payload,
        "display_link": display_link(venue.place, fallback_query=venue.manual_address),
    }


async def save_venue_location(
    session: AsyncSession, *, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Persist a venue location for an activity.

    ``place=None`` is a first-class outcome, not an error: the row is written
    with the manual address and a ``failed``/``skipped`` geocode status.
    """

    activity_id = UUID(str(payload["activity_id"]))
    raw_place = payload.get("place")
    place: NormalizedPlace | None = None
    if raw_place:
        try:
            assert_no_provider_leakage(raw_place)
            place = NormalizedPlace(
                formatted_address=str(raw_place["formatted_address"]),
                country_code=str(raw_place.get("country_code") or ""),
                region_code=raw_place.get("region_code"),
                city_code=normalize_city_code(raw_place.get("city_code")),
                latitude=raw_place.get("latitude"),
                longitude=raw_place.get("longitude"),
                provider=str(raw_place["provider"]),
                provider_place_ref=raw_place.get("provider_place_ref"),
            )
        except (DiscoveryRuleError, KeyError) as error:
            if isinstance(error, DiscoveryRuleError):
                raise _fail(error) from error
            raise VavError(
                "PLACE_PAYLOAD_INCOMPLETE",
                "A place payload requires formatted_address and provider.",
                status_code=422,
            ) from error
    try:
        venue = resolve_venue_location(
            manual_address=payload["manual_address"],
            place=place,
            failure_code=payload.get("failure_code"),
            attempted=bool(payload.get("attempted", True)),
        )
    except DiscoveryRuleError as error:
        raise _fail(error) from error

    await session.execute(
        text(
            "INSERT INTO activity_venue_locations "
            "(activity_id,manual_address,formatted_address,country_code,region_code,city_code,"
            "latitude,longitude,provider,provider_place_ref,geocode_status,failure_code,geocoded_at,updated_by) "
            "VALUES (:activity_id,:manual_address,:formatted_address,:country_code,:region_code,:city_code,"
            ":latitude,:longitude,:provider,:provider_place_ref,:geocode_status,:failure_code,:geocoded_at,:actor) "
            "ON CONFLICT (activity_id) DO UPDATE SET manual_address=EXCLUDED.manual_address,"
            "formatted_address=EXCLUDED.formatted_address,country_code=EXCLUDED.country_code,"
            "region_code=EXCLUDED.region_code,city_code=EXCLUDED.city_code,latitude=EXCLUDED.latitude,"
            "longitude=EXCLUDED.longitude,provider=EXCLUDED.provider,provider_place_ref=EXCLUDED.provider_place_ref,"
            "geocode_status=EXCLUDED.geocode_status,failure_code=EXCLUDED.failure_code,"
            "geocoded_at=EXCLUDED.geocoded_at,updated_by=EXCLUDED.updated_by,updated_at=now()"
        ),
        {
            "activity_id": str(activity_id),
            "manual_address": venue.manual_address,
            "formatted_address": venue.place.formatted_address if venue.place else None,
            "country_code": venue.place.country_code if venue.place else None,
            "region_code": venue.place.region_code if venue.place else None,
            "city_code": venue.place.city_code if venue.place else None,
            "latitude": venue.place.latitude if venue.place else None,
            "longitude": venue.place.longitude if venue.place else None,
            "provider": venue.place.provider if venue.place else None,
            "provider_place_ref": venue.place.provider_place_ref if venue.place else None,
            "geocode_status": venue.geocode_status.value,
            "failure_code": venue.failure_code,
            "geocoded_at": _now() if venue.geocode_status is GeocodeStatus.RESOLVED else None,
            "actor": str(actor_id),
        },
    )
    await _audit(
        session,
        subject_type="activity_venue_location",
        subject_id=activity_id,
        actor_id=actor_id,
        actor_kind="admin",
        action="venue_location.saved",
        metadata={"geocode_status": venue.geocode_status.value, "failure_code": venue.failure_code},
    )
    await session.commit()
    return _venue_payload(venue)


async def get_venue_location(session: AsyncSession, activity_id: UUID) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT manual_address,formatted_address,country_code,region_code,city_code,"
                    "latitude,longitude,provider,provider_place_ref,geocode_status,failure_code "
                    "FROM activity_venue_locations WHERE activity_id=:activity_id"
                ),
                {"activity_id": str(activity_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("VENUE_LOCATION_NOT_FOUND", "No venue location recorded.", status_code=404)
    place = (
        NormalizedPlace(
            formatted_address=row["formatted_address"],
            country_code=row["country_code"] or "",
            region_code=row["region_code"],
            city_code=row["city_code"],
            latitude=float(row["latitude"]) if row["latitude"] is not None else None,
            longitude=float(row["longitude"]) if row["longitude"] is not None else None,
            provider=row["provider"],
            provider_place_ref=row["provider_place_ref"],
        )
        if row["formatted_address"] and row["provider"]
        else None
    )
    return _venue_payload(
        resolve_venue_location(
            manual_address=row["manual_address"],
            place=place,
            failure_code=row["failure_code"],
            attempted=row["geocode_status"] != GeocodeStatus.SKIPPED.value,
        )
    )


# ---------------------------------------------------------------------------
# SHARE-001 share cards, short links, QR
# ---------------------------------------------------------------------------


async def _activity_share_state(session: AsyncSession, activity_id: UUID) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT a.id,loc.title,loc.summary AS subtitle,a.starts_at,"
                    "loc.cover_media_id::text AS cover_image_url,a.status,a.visibility,"
                    "v.city_code FROM activities a "
                    "LEFT JOIN activity_localizations loc ON loc.activity_id=a.id AND loc.locale=a.default_locale "
                    "LEFT JOIN activity_venue_locations v ON v.activity_id=a.id WHERE a.id=:id"
                ),
                {"id": str(activity_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("ACTIVITY_NOT_FOUND", "Activity not found.", status_code=404)
    return dict(row)


async def create_share_card(
    session: AsyncSession, *, activity_id: UUID, actor_id: UUID | None, payload: dict[str, Any]
) -> dict[str, Any]:
    """Build (or refresh) the deterministic share card and its signed link.

    Idempotent for a given ``(activity_id, card_version)``: the card payload and
    fingerprint are computed by the domain, so a second call stores the same
    bytes and reuses the same short code.
    """

    require_sharing_enabled()
    settings = get_settings()
    activity = await _activity_share_state(session, activity_id)
    card_version = int(payload.get("card_version", 1))
    try:
        card = build_share_card(
            event_id=activity_id,
            card_version=card_version,
            title=activity["title"],
            subtitle=activity.get("subtitle"),
            city_code=activity.get("city_code"),
            starts_at=activity["starts_at"],
            base_url=settings.share_public_base_url,
            cover_image_url=activity.get("cover_image_url"),
            publication_status=activity["status"],
            visibility=activity["visibility"],
            sharing_enabled=True,
        )
        link = issue_share_link(
            event_id=activity_id,
            share_version=card_version,
            base_url=settings.share_public_base_url,
            secret=_secret_value(settings.share_link_secret),
            issued_at=_now(),
            ttl_hours=payload.get("ttl_hours", settings.share_link_default_ttl_hours),
            publication_status=activity["status"],
            visibility=activity["visibility"],
            sharing_enabled=True,
        )
        qr_target = build_qr_target(
            canonical_url=card.canonical_url,
            short_code=link.short_code,
            campaign=payload.get("campaign"),
        )
        assert_qr_target_is_canonical(qr_target, canonical_url=card.canonical_url)
    except DiscoveryRuleError as error:
        raise _fail(error, status_code=409) from error

    await session.execute(
        text(
            "INSERT INTO activity_share_cards "
            "(activity_id,card_version,fingerprint,payload,cover_is_fallback,created_by) "
            "VALUES (:activity_id,:card_version,:fingerprint,CAST(:payload AS jsonb),:cover_is_fallback,:actor) "
            "ON CONFLICT (activity_id, card_version) DO UPDATE SET fingerprint=EXCLUDED.fingerprint,"
            "payload=EXCLUDED.payload,cover_is_fallback=EXCLUDED.cover_is_fallback,updated_at=now()"
        ),
        {
            "activity_id": str(activity_id),
            "card_version": card_version,
            "fingerprint": card.fingerprint,
            "payload": _json(card.as_payload()),
            "cover_is_fallback": card.cover_is_fallback,
            "actor": str(actor_id) if actor_id else None,
        },
    )
    await session.execute(
        text(
            "INSERT INTO activity_share_links "
            "(activity_id,share_version,short_code,signature,canonical_url,expires_at,created_by) "
            "VALUES (:activity_id,:share_version,:short_code,:signature,:canonical_url,:expires_at,:actor) "
            "ON CONFLICT (short_code) DO UPDATE SET signature=EXCLUDED.signature,"
            "canonical_url=EXCLUDED.canonical_url,expires_at=EXCLUDED.expires_at,"
            "revoked_at=NULL,revoked_reason=NULL,updated_at=now()"
        ),
        {
            "activity_id": str(activity_id),
            "share_version": card_version,
            "short_code": link.short_code,
            "signature": link.signature,
            "canonical_url": link.canonical_url,
            "expires_at": link.expires_at,
            "actor": str(actor_id) if actor_id else None,
        },
    )
    await _publish(
        session,
        "activity.share_card.created.v1",
        "activity",
        activity_id,
        {
            "activity_id": str(activity_id),
            "card_version": card_version,
            "fingerprint": card.fingerprint,
            "short_code": link.short_code,
        },
    )
    await session.commit()
    return {
        "card": card.as_payload(),
        "fingerprint": card.fingerprint,
        "short_code": link.short_code,
        "canonical_url": card.canonical_url,
        "qr_target": qr_target,
        "expires_at": link.expires_at,
    }


async def get_share_card(session: AsyncSession, *, activity_id: UUID) -> dict[str, Any]:
    require_sharing_enabled()
    activity = await _activity_share_state(session, activity_id)
    try:
        ensure_event_shareable(
            publication_status=activity["status"], visibility=activity["visibility"]
        )
    except DiscoveryRuleError as error:
        # 404 rather than 403: a member with a stale link must not learn that a
        # draft event exists at this id.
        raise _fail(error, status_code=404) from error
    row = (
        (
            await session.execute(
                text(
                    "SELECT card_version,fingerprint,payload,cover_is_fallback "
                    "FROM activity_share_cards WHERE activity_id=:activity_id "
                    "ORDER BY card_version DESC LIMIT 1"
                ),
                {"activity_id": str(activity_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError(
            "SHARE_CARD_NOT_FOUND",
            "No share card has been generated.",
            status_code=404,
        )
    link = (
        (
            await session.execute(
                text(
                    "SELECT short_code,canonical_url,expires_at FROM activity_share_links "
                    "WHERE activity_id=:activity_id AND share_version=:version AND revoked_at IS NULL"
                ),
                {"activity_id": str(activity_id), "version": row["card_version"]},
            )
        )
        .mappings()
        .first()
    )
    canonical = (
        link["canonical_url"]
        if link
        else canonical_event_url(get_settings().share_public_base_url, activity_id)
    )
    return {
        "card": row["payload"],
        "fingerprint": row["fingerprint"],
        "cover_is_fallback": row["cover_is_fallback"],
        "short_code": link["short_code"] if link else None,
        "canonical_url": canonical,
        "qr_target": build_qr_target(
            canonical_url=canonical, short_code=link["short_code"] if link else None
        ),
        "expires_at": link["expires_at"] if link else None,
    }


async def resolve_short_link(session: AsyncSession, *, short_code: str) -> dict[str, Any]:
    """Resolve a short code to the canonical event URL.

    Publication and visibility are re-checked here, not merely at issue time, so
    an event taken down after a link was shared stops resolving (SHARE-001).
    """

    require_sharing_enabled()
    settings = get_settings()
    row = (
        (
            await session.execute(
                text(
                    "SELECT activity_id,share_version,short_code,signature,canonical_url,expires_at,"
                    "revoked_at FROM activity_share_links WHERE short_code=:short_code"
                ),
                {"short_code": short_code},
            )
        )
        .mappings()
        .first()
    )
    if row is None or row["revoked_at"] is not None:
        raise VavError("SHARE_LINK_NOT_FOUND", "This share link is not valid.", status_code=404)
    activity_id = UUID(str(row["activity_id"]))
    expected_code = short_link_code(
        activity_id,
        int(row["share_version"]),
        secret=_secret_value(settings.share_link_secret),
    )
    signed_payload = {
        "event_id": str(activity_id),
        "share_version": int(row["share_version"]),
        "short_code": row["short_code"],
        "expires_at": row["expires_at"].astimezone(UTC).isoformat() if row["expires_at"] else None,
    }
    if expected_code != row["short_code"] or not verify_share_token(
        signed_payload,
        row["signature"],
        secret=_secret_value(settings.share_link_secret),
    ):
        raise VavError(
            "SHARE_LINK_SIGNATURE_INVALID",
            "This share link is not valid.",
            status_code=400,
        )
    if row["expires_at"] is not None and _now() > row["expires_at"]:
        raise VavError("SHARE_LINK_EXPIRED", "This share link has expired.", status_code=410)
    activity = await _activity_share_state(session, activity_id)
    try:
        ensure_event_shareable(
            publication_status=activity["status"], visibility=activity["visibility"]
        )
    except DiscoveryRuleError as error:
        raise _fail(error, status_code=410) from error
    await session.execute(
        text(
            "INSERT INTO activity_share_resolutions (activity_id,short_code) "
            "VALUES (:activity_id,:short_code)"
        ),
        {"activity_id": str(activity_id), "short_code": short_code},
    )
    await session.commit()
    return {
        "activity_id": str(activity_id),
        "canonical_url": row["canonical_url"],
        "qr_target": build_qr_target(
            canonical_url=row["canonical_url"], short_code=row["short_code"]
        ),
    }


async def revoke_share_links(
    session: AsyncSession, *, activity_id: UUID, actor_id: UUID, reason: str
) -> dict[str, Any]:
    """Revoke every live link for an activity.

    Used when an event is unpublished or its copy is corrected. Rows are marked
    revoked rather than deleted so a support question about a dead link can
    still be answered.
    """

    result = await session.execute(
        text(
            "UPDATE activity_share_links SET revoked_at=now(),revoked_reason=:reason,updated_at=now() "
            "WHERE activity_id=:activity_id AND revoked_at IS NULL"
        ),
        {"activity_id": str(activity_id), "reason": reason},
    )
    await _audit(
        session,
        subject_type="activity",
        subject_id=activity_id,
        actor_id=actor_id,
        actor_kind="admin",
        action="share_links.revoked",
        reason=reason,
        metadata={"revoked": int(getattr(result, "rowcount", 0) or 0) or 0},
    )
    await _publish(
        session,
        "activity.share_links.revoked.v1",
        "activity",
        activity_id,
        {"activity_id": str(activity_id), "revoked": int(getattr(result, "rowcount", 0) or 0) or 0},
    )
    await session.commit()
    return {
        "activity_id": str(activity_id),
        "revoked": int(getattr(result, "rowcount", 0) or 0) or 0,
    }


async def upsert_map_provider_config(
    session: AsyncSession, *, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Pin a country to a provider.

    Only the provider *choice* is stored. Credentials stay in server-side
    settings, so this table can be read by anyone with admin access without
    exposing a key (MAP-001).
    """

    country = str(payload["country_code"]).upper()
    await session.execute(
        text(
            "INSERT INTO map_provider_configs (country_code,provider,is_active,updated_by) "
            "VALUES (:country_code,:provider,:is_active,:actor) "
            "ON CONFLICT (country_code) DO UPDATE SET provider=EXCLUDED.provider,"
            "is_active=EXCLUDED.is_active,updated_by=EXCLUDED.updated_by,updated_at=now()"
        ),
        {
            "country_code": country,
            "provider": payload["provider"],
            "is_active": bool(payload.get("is_active", True)),
            "actor": str(actor_id),
        },
    )
    await _audit(
        session,
        subject_type="map_provider_config",
        subject_id=None,
        actor_id=actor_id,
        actor_kind="admin",
        action="map_provider.configured",
        metadata={"country_code": country, "provider": payload["provider"]},
    )
    await session.commit()
    return {
        "country_code": country,
        "provider": payload["provider"],
        "is_active": bool(payload.get("is_active", True)),
    }


async def list_map_provider_configs(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT country_code,provider,is_active,updated_at FROM map_provider_configs "
                    "ORDER BY country_code"
                )
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


async def location_debug(
    session: AsyncSession, *, user_id: UUID | None, ip_city_code: str | None
) -> dict[str, Any]:
    """Operator view of how a city was resolved, for support tickets."""

    resolved = await resolve_location(session, user_id=user_id, ip_city_code=ip_city_code)
    return {
        "city_code": resolved.city_code,
        "source": resolved.source.value,
        "is_confirmed": resolved.is_confirmed,
        "suggested_city_code": resolved.suggested_city_code,
        "reason_code": resolved.reason_code,
        "manual_wins": resolved.source is LocationSource.MANUAL,
    }
