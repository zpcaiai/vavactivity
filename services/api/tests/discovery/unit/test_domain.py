"""Pure-domain tests for discovery rules (GEO-001 / MAP-001 / SHARE-001).

These tests deliberately touch no database, no settings and no network, so they
run on any machine including one without PostgreSQL or Redis.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from vav.modules.discovery.domain import (
    DEFAULT_COVER_PLACEHOLDER,
    IP_MARKER_LENGTH,
    SHORT_CODE_LENGTH,
    DiscoveryRuleError,
    EventPublicationStatus,
    FallbackReason,
    GeocodeStatus,
    LocationSource,
    MapProviderCode,
    ResultScope,
    assert_no_provider_leakage,
    assert_qr_target_is_canonical,
    build_ip_hint_record,
    build_qr_target,
    build_share_card,
    canonical_event_url,
    coarse_ip_marker,
    display_link,
    ensure_event_shareable,
    ensure_preference_is_persistable,
    is_event_shareable,
    issue_share_link,
    normalize_city_code,
    normalize_geocode_result,
    plan_result_scope,
    reject_precise_location_fields,
    resolve_cover_image,
    resolve_discovery_location,
    resolve_share_link,
    resolve_venue_location,
    short_link_code,
    sign_share_token,
    verify_share_token,
)

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
EVENT_ID = UUID(int=42)
BASE_URL = "https://vav.example.com"
SECRET = "unit-test-share-secret"

AMAP_RAW = {
    "formatted_address": "Shanghai, Jing'an District, 1 Test Road",
    "adcode": "310106",
    "province_adcode": "310000",
    "location": "121.4737,31.2304",
    "id": "B0FFHQ1234",
    "level": "poi",
    "citycode": "021",
}

GOOGLE_RAW = {
    "formatted_address": "1 Test Road, Singapore",
    "place_id": "ChIJtestplaceid",
    "geometry": {"location": {"lat": 1.3521, "lng": 103.8198}},
    "address_components": [
        {"short_name": "SG", "types": ["country", "political"]},
        {"short_name": "Central", "types": ["administrative_area_level_1"]},
        {"short_name": "SIN", "types": ["locality"]},
    ],
    "partial_match": True,
}


# ---------------------------------------------------------------------------
# GEO-001 manual preference beats IP
# ---------------------------------------------------------------------------


def test_manual_city_preference_wins_over_the_ip_suggestion() -> None:
    resolved = resolve_discovery_location(manual_city_code="310000", ip_city_code="440300")
    assert resolved.city_code == "310000"
    assert resolved.source is LocationSource.MANUAL
    assert resolved.is_confirmed is True
    # The IP city is still reported so the UI can offer to switch, but it never
    # takes effect on its own.
    assert resolved.suggested_city_code == "440300"


def test_ip_city_is_only_an_unconfirmed_suggestion() -> None:
    resolved = resolve_discovery_location(manual_city_code=None, ip_city_code="440300")
    assert resolved.city_code == "440300"
    assert resolved.source is LocationSource.IP_SUGGESTION
    assert resolved.is_confirmed is False
    assert resolved.reason_code == "IP_SUGGESTION_UNCONFIRMED"


def test_ip_suggestion_can_be_switched_off_and_collapses_to_no_city() -> None:
    resolved = resolve_discovery_location(
        manual_city_code=None, ip_city_code="440300", allow_ip_suggestion=False
    )
    assert resolved.city_code is None
    assert resolved.source is LocationSource.NONE


def test_an_ip_suggestion_may_never_be_persisted_as_a_preference() -> None:
    resolved = resolve_discovery_location(manual_city_code=None, ip_city_code="440300")
    with pytest.raises(DiscoveryRuleError) as excinfo:
        ensure_preference_is_persistable(resolved)
    assert excinfo.value.code == "LOCATION_NOT_PERSISTABLE"


def test_a_manual_preference_is_persistable() -> None:
    resolved = resolve_discovery_location(manual_city_code=" 310000 ")
    assert ensure_preference_is_persistable(resolved) == "310000"


def test_city_codes_are_normalized_and_validated() -> None:
    assert normalize_city_code(" cn-310000 ") == "CN-310000"
    assert normalize_city_code("   ") is None
    with pytest.raises(DiscoveryRuleError) as excinfo:
        normalize_city_code("shang hai")
    assert excinfo.value.code == "CITY_CODE_INVALID"


# ---------------------------------------------------------------------------
# GEO-001 no precise IP-derived location is persisted
# ---------------------------------------------------------------------------


def test_ip_marker_is_truncated_hashed_and_never_the_address() -> None:
    marker = coarse_ip_marker("203.0.113.7", salt="pepper")
    assert marker is not None
    assert len(marker) == IP_MARKER_LENGTH
    assert "203.0.113.7" not in marker
    # Deterministic for rate limiting...
    assert marker == coarse_ip_marker("203.0.113.7", salt="pepper")
    # ...but salt-scoped, so it cannot be joined against another system's logs.
    assert marker != coarse_ip_marker("203.0.113.7", salt="other")


def test_ip_marker_requires_a_salt_and_tolerates_a_missing_ip() -> None:
    assert coarse_ip_marker(None, salt="pepper") is None
    with pytest.raises(DiscoveryRuleError) as excinfo:
        coarse_ip_marker("203.0.113.7", salt="")
    assert excinfo.value.code == "IP_MARKER_SALT_REQUIRED"


def test_ip_hint_record_holds_only_a_coarse_city_and_a_marker() -> None:
    record = build_ip_hint_record(ip_address="203.0.113.7", city_code="440300", salt="pepper")
    assert set(record) == {"city_code", "ip_marker"}
    assert record["city_code"] == "440300"
    reject_precise_location_fields(record)


def test_persisting_a_precise_ip_location_is_rejected() -> None:
    with pytest.raises(DiscoveryRuleError) as excinfo:
        reject_precise_location_fields(
            {"city_code": "440300", "latitude": 22.5, "ip_address": "203.0.113.7"}
        )
    assert excinfo.value.code == "IP_LOCATION_TOO_PRECISE"
    assert excinfo.value.details["fields"] == ["ip_address", "latitude"]


# ---------------------------------------------------------------------------
# GEO-001 national fallback explains itself
# ---------------------------------------------------------------------------


def test_local_results_are_used_when_the_city_has_events() -> None:
    resolved = resolve_discovery_location(manual_city_code="310000")
    plan = plan_result_scope(resolved=resolved, local_count=4)
    assert plan.scope is ResultScope.LOCAL
    assert plan.fallback_applied is False
    assert plan.fallback_reason is FallbackReason.NOT_APPLIED


def test_empty_local_result_falls_back_to_national_and_says_why() -> None:
    resolved = resolve_discovery_location(manual_city_code="310000")
    plan = plan_result_scope(resolved=resolved, local_count=0)
    assert plan.scope is ResultScope.NATIONAL
    assert plan.fallback_applied is True
    assert plan.fallback_reason is FallbackReason.LOCAL_RESULTS_EMPTY
    assert plan.city_code == "310000"


def test_no_resolvable_city_falls_back_with_its_own_reason() -> None:
    resolved = resolve_discovery_location(manual_city_code=None, ip_city_code=None)
    plan = plan_result_scope(resolved=resolved, local_count=0)
    assert plan.fallback_reason is FallbackReason.NO_CITY_RESOLVED


def test_a_thin_local_result_can_fall_back_below_a_configured_minimum() -> None:
    resolved = resolve_discovery_location(manual_city_code="310000")
    plan = plan_result_scope(resolved=resolved, local_count=2, minimum_local_results=5)
    assert plan.fallback_reason is FallbackReason.LOCAL_BELOW_MINIMUM
    assert plan.local_count == 2


def test_invalid_scope_inputs_are_rejected() -> None:
    resolved = resolve_discovery_location(manual_city_code="310000")
    with pytest.raises(DiscoveryRuleError):
        plan_result_scope(resolved=resolved, local_count=-1)
    with pytest.raises(DiscoveryRuleError):
        plan_result_scope(resolved=resolved, local_count=1, minimum_local_results=0)


# ---------------------------------------------------------------------------
# MAP-001 provider selection behind flags
# ---------------------------------------------------------------------------


def test_chinese_events_use_amap_and_others_use_google() -> None:
    from vav.modules.discovery.domain import select_map_provider

    assert select_map_provider("CN", amap_enabled=True, google_enabled=True) is MapProviderCode.AMAP
    assert (
        select_map_provider("SG", amap_enabled=True, google_enabled=True)
        is MapProviderCode.GOOGLE_MAPS
    )


def test_a_disabled_preferred_provider_falls_back_to_the_other_one() -> None:
    from vav.modules.discovery.domain import select_map_provider

    assert (
        select_map_provider("CN", amap_enabled=False, google_enabled=True)
        is MapProviderCode.GOOGLE_MAPS
    )


def test_no_enabled_provider_is_an_error_not_a_silent_default() -> None:
    from vav.modules.discovery.domain import select_map_provider

    with pytest.raises(DiscoveryRuleError) as excinfo:
        select_map_provider("CN", amap_enabled=False, google_enabled=False)
    assert excinfo.value.code == "MAP_PROVIDER_UNAVAILABLE"


# ---------------------------------------------------------------------------
# MAP-001 normalization keeps provider fields out of the domain
# ---------------------------------------------------------------------------


def test_amap_payload_is_normalized_into_the_shared_shape() -> None:
    place = normalize_geocode_result(MapProviderCode.AMAP, AMAP_RAW)
    assert place.country_code == "CN"
    assert place.city_code == "310106"
    assert place.latitude == pytest.approx(31.2304)
    assert place.longitude == pytest.approx(121.4737)
    assert place.provider == "amap"
    assert place.provider_place_ref == "B0FFHQ1234"


def test_google_payload_is_normalized_into_the_same_shape() -> None:
    place = normalize_geocode_result(MapProviderCode.GOOGLE_MAPS, GOOGLE_RAW)
    assert place.country_code == "SG"
    assert place.region_code == "Central"
    assert place.city_code == "SIN"
    assert place.provider_place_ref == "ChIJtestplaceid"


def test_provider_specific_keys_never_survive_normalization() -> None:
    for provider, raw in (
        (MapProviderCode.AMAP, AMAP_RAW),
        (MapProviderCode.GOOGLE_MAPS, GOOGLE_RAW),
    ):
        payload = normalize_geocode_result(provider, raw).as_payload()
        assert "adcode" not in payload
        assert "place_id" not in payload
        assert "geometry" not in payload
        assert "partial_match" not in payload
        assert_no_provider_leakage(payload)


def test_a_payload_with_extra_keys_is_rejected_as_a_leak() -> None:
    payload = normalize_geocode_result(MapProviderCode.AMAP, AMAP_RAW).as_payload()
    payload["amap_api_key"] = "secret"
    with pytest.raises(DiscoveryRuleError) as excinfo:
        assert_no_provider_leakage(payload)
    assert excinfo.value.code == "PLACE_PAYLOAD_LEAK"


def test_a_provider_result_with_no_address_is_a_geocode_failure() -> None:
    with pytest.raises(DiscoveryRuleError) as excinfo:
        normalize_geocode_result(MapProviderCode.AMAP, {"location": "121.0,31.0"})
    assert excinfo.value.code == "GEOCODE_ADDRESS_MISSING"


def test_out_of_range_coordinates_are_rejected() -> None:
    with pytest.raises(DiscoveryRuleError) as excinfo:
        normalize_geocode_result(
            MapProviderCode.AMAP, {**AMAP_RAW, "location": "121.4737,931.2304"}
        )
    assert excinfo.value.code == "GEOCODE_COORDINATE_OUT_OF_RANGE"


# ---------------------------------------------------------------------------
# MAP-001 a geocode failure preserves the manual address
# ---------------------------------------------------------------------------


def test_geocode_failure_preserves_the_manually_entered_address() -> None:
    venue = resolve_venue_location(
        manual_address="  1 Test Road, Jing'an, Shanghai  ",
        place=None,
        failure_code="GEOCODE_TIMEOUT",
    )
    assert venue.geocode_status is GeocodeStatus.FAILED
    assert venue.manual_address == "1 Test Road, Jing'an, Shanghai"
    assert venue.display_address == "1 Test Road, Jing'an, Shanghai"
    assert venue.failure_code == "GEOCODE_TIMEOUT"


def test_a_successful_geocode_prefers_the_canonical_address() -> None:
    place = normalize_geocode_result(MapProviderCode.AMAP, AMAP_RAW)
    venue = resolve_venue_location(manual_address="1 test rd", place=place)
    assert venue.geocode_status is GeocodeStatus.RESOLVED
    assert venue.display_address == AMAP_RAW["formatted_address"]
    # The operator's own text is still kept, so nothing is lost.
    assert venue.manual_address == "1 test rd"


def test_skipping_geocoding_is_distinct_from_failing_it() -> None:
    venue = resolve_venue_location(manual_address="1 test rd", place=None, attempted=False)
    assert venue.geocode_status is GeocodeStatus.SKIPPED
    assert venue.failure_code is None


def test_a_venue_with_no_address_at_all_is_rejected() -> None:
    with pytest.raises(DiscoveryRuleError) as excinfo:
        resolve_venue_location(manual_address="   ", place=None)
    assert excinfo.value.code == "VENUE_ADDRESS_REQUIRED"


def test_display_link_is_provider_aware_and_carries_no_api_key() -> None:
    amap = display_link(
        normalize_geocode_result(MapProviderCode.AMAP, AMAP_RAW), fallback_query="x"
    )
    google = display_link(
        normalize_geocode_result(MapProviderCode.GOOGLE_MAPS, GOOGLE_RAW), fallback_query="x"
    )
    assert amap is not None and amap.startswith("https://uri.amap.com/")
    assert google is not None and google.startswith("https://www.google.com/maps/")
    for link in (amap, google):
        assert "key=" not in link
    assert display_link(None, fallback_query="x") is None


# ---------------------------------------------------------------------------
# SHARE-001 an unpublished event can never be shared
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status",
    ["draft", "pending_review", "unpublished", "cancelled", "archived"],
)
def test_an_unpublished_event_cannot_be_shared(status: str) -> None:
    with pytest.raises(DiscoveryRuleError) as excinfo:
        ensure_event_shareable(publication_status=status, visibility="public")
    assert excinfo.value.code == "SHARE_EVENT_NOT_PUBLISHED"
    assert is_event_shareable(publication_status=status, visibility="public") is False


@pytest.mark.parametrize("visibility", ["private", "unlisted"])
def test_a_non_public_event_cannot_be_shared_publicly(visibility: str) -> None:
    with pytest.raises(DiscoveryRuleError) as excinfo:
        ensure_event_shareable(publication_status="published", visibility=visibility)
    assert excinfo.value.code == "SHARE_EVENT_NOT_PUBLIC"


def test_an_unknown_status_fails_closed() -> None:
    with pytest.raises(DiscoveryRuleError) as excinfo:
        ensure_event_shareable(publication_status="who_knows", visibility="public")
    assert excinfo.value.code == "SHARE_STATUS_UNKNOWN"


def test_the_sharing_feature_flag_gates_everything() -> None:
    with pytest.raises(DiscoveryRuleError) as excinfo:
        ensure_event_shareable(
            publication_status="published", visibility="public", sharing_enabled=False
        )
    assert excinfo.value.code == "SHARE_DISABLED"


def test_building_a_card_for_a_draft_event_is_refused() -> None:
    with pytest.raises(DiscoveryRuleError) as excinfo:
        build_share_card(
            event_id=EVENT_ID,
            card_version=1,
            title="Test event",
            starts_at=NOW,
            base_url=BASE_URL,
            publication_status=EventPublicationStatus.DRAFT.value,
            visibility="public",
        )
    assert excinfo.value.code == "SHARE_EVENT_NOT_PUBLISHED"


def test_issuing_a_link_for_a_draft_event_is_refused() -> None:
    with pytest.raises(DiscoveryRuleError):
        issue_share_link(
            event_id=EVENT_ID,
            share_version=1,
            base_url=BASE_URL,
            secret=SECRET,
            issued_at=NOW,
            publication_status="draft",
            visibility="public",
        )


# ---------------------------------------------------------------------------
# SHARE-001 deterministic cards with a cover fallback
# ---------------------------------------------------------------------------


def _card(**overrides: object):
    kwargs: dict = {
        "event_id": EVENT_ID,
        "card_version": 1,
        "title": "Test event",
        "subtitle": "Shanghai meetup",
        "city_code": "310000",
        "starts_at": NOW,
        "base_url": BASE_URL,
        "cover_image_url": "https://cdn.example.com/cover.jpg",
        "publication_status": "published",
        "visibility": "public",
    }
    kwargs.update(overrides)
    return build_share_card(**kwargs)  # type: ignore[arg-type]


def test_the_same_event_and_version_always_produce_the_same_payload() -> None:
    first, second = _card(), _card()
    assert first.as_payload() == second.as_payload()
    assert first.fingerprint == second.fingerprint


def test_a_new_card_version_changes_the_fingerprint() -> None:
    assert _card().fingerprint != _card(card_version=2).fingerprint


def test_the_card_payload_is_snapshot_stable_across_timezones() -> None:
    """The same instant expressed in Asia/Shanghai must not change the hash."""

    shanghai = NOW.astimezone(timezone(timedelta(hours=8)))
    assert _card(starts_at=shanghai).fingerprint == _card().fingerprint


def test_a_missing_cover_image_degrades_gracefully() -> None:
    card = _card(cover_image_url=None)
    assert card.cover_image_url == DEFAULT_COVER_PLACEHOLDER
    assert card.cover_is_fallback is True
    assert resolve_cover_image("  ").is_fallback is True
    assert resolve_cover_image("https://cdn/x.jpg").is_fallback is False


def test_a_card_requires_a_title_and_an_aware_start_time() -> None:
    with pytest.raises(DiscoveryRuleError) as excinfo:
        _card(title="   ")
    assert excinfo.value.code == "SHARE_TITLE_REQUIRED"
    with pytest.raises(DiscoveryRuleError) as excinfo:
        _card(starts_at=datetime(2026, 8, 12, 12, 0))
    assert excinfo.value.code == "SHARE_NAIVE_DATETIME"


# ---------------------------------------------------------------------------
# SHARE-001 signed short links and QR targets
# ---------------------------------------------------------------------------


def test_a_short_code_is_deterministic_keyed_and_short() -> None:
    code = short_link_code(EVENT_ID, 1, secret=SECRET)
    assert len(code) == SHORT_CODE_LENGTH
    assert code == short_link_code(EVENT_ID, 1, secret=SECRET)
    assert code != short_link_code(EVENT_ID, 2, secret=SECRET)
    assert code != short_link_code(EVENT_ID, 1, secret="another-secret")


def test_a_share_signature_round_trips_and_rejects_tampering() -> None:
    payload = {"event_id": str(EVENT_ID), "share_version": 1}
    signature = sign_share_token(payload, secret=SECRET)
    assert verify_share_token(payload, signature, secret=SECRET) is True
    assert verify_share_token({**payload, "share_version": 2}, signature, secret=SECRET) is False
    assert verify_share_token(payload, "", secret=SECRET) is False


def _link(**overrides: object):
    kwargs: dict = {
        "event_id": EVENT_ID,
        "share_version": 1,
        "base_url": BASE_URL,
        "secret": SECRET,
        "issued_at": NOW,
        "publication_status": "published",
        "visibility": "public",
    }
    kwargs.update(overrides)
    return issue_share_link(**kwargs)  # type: ignore[arg-type]


def test_a_valid_link_resolves_to_the_canonical_url() -> None:
    link = _link()
    resolved = resolve_share_link(
        link=link,
        event_id=EVENT_ID,
        share_version=1,
        secret=SECRET,
        now=NOW + timedelta(hours=1),
        publication_status="published",
        visibility="public",
    )
    assert resolved == canonical_event_url(BASE_URL, EVENT_ID)


def test_an_expired_link_stops_resolving() -> None:
    link = _link(ttl_hours=1)
    with pytest.raises(DiscoveryRuleError) as excinfo:
        resolve_share_link(
            link=link,
            event_id=EVENT_ID,
            share_version=1,
            secret=SECRET,
            now=NOW + timedelta(hours=2),
            publication_status="published",
            visibility="public",
        )
    assert excinfo.value.code == "SHARE_LINK_EXPIRED"


def test_unpublishing_an_event_kills_links_that_were_already_shared() -> None:
    """The difference between a share link and a permanent leak (SHARE-001)."""

    link = _link()
    with pytest.raises(DiscoveryRuleError) as excinfo:
        resolve_share_link(
            link=link,
            event_id=EVENT_ID,
            share_version=1,
            secret=SECRET,
            now=NOW + timedelta(hours=1),
            publication_status="unpublished",
            visibility="public",
        )
    assert excinfo.value.code == "SHARE_EVENT_NOT_PUBLISHED"


def test_a_forged_signature_does_not_resolve() -> None:
    link = _link()
    forged = type(link)(
        short_code=link.short_code,
        signature="0" * 64,
        canonical_url=link.canonical_url,
        expires_at=link.expires_at,
    )
    with pytest.raises(DiscoveryRuleError) as excinfo:
        resolve_share_link(
            link=forged,
            event_id=EVENT_ID,
            share_version=1,
            secret=SECRET,
            now=NOW,
            publication_status="published",
            visibility="public",
        )
    assert excinfo.value.code == "SHARE_LINK_SIGNATURE_INVALID"


def test_the_canonical_url_must_be_https() -> None:
    with pytest.raises(DiscoveryRuleError) as excinfo:
        canonical_event_url("http://vav.example.com", EVENT_ID)
    assert excinfo.value.code == "SHARE_BASE_URL_INSECURE"


def test_the_qr_target_is_always_the_canonical_event_url() -> None:
    canonical = canonical_event_url(BASE_URL, EVENT_ID)
    target = build_qr_target(canonical_url=canonical, short_code="ABCDEFGHIJ", campaign="poster")
    assert target.startswith(canonical)
    assert "s=ABCDEFGHIJ" in target
    assert_qr_target_is_canonical(target, canonical_url=canonical)


def test_a_qr_target_that_points_at_a_redirector_is_rejected() -> None:
    with pytest.raises(DiscoveryRuleError) as excinfo:
        build_qr_target(canonical_url="https://vav.example.com/s/ABCDEFGHIJ")
    assert excinfo.value.code == "QR_TARGET_NOT_CANONICAL"
    with pytest.raises(DiscoveryRuleError):
        assert_qr_target_is_canonical(
            "https://evil.example.com/events/42",
            canonical_url=canonical_event_url(BASE_URL, EVENT_ID),
        )
