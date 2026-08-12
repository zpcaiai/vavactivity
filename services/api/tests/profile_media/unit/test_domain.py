"""Pure-domain tests for profile media rules (PROFILE-001).

These tests deliberately touch no database, no settings and no network, so they
run on any machine including one without PostgreSQL or object storage. They pin
the server-side upload limits, the pending-by-default moderation state, the
unpredictable private-media addressing and the consent-scoped share projection.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from vav.modules.profile_media.domain import (
    ASSET_TOKEN_LENGTH,
    COMPLETENESS_WEIGHTS,
    DEFAULT_MODERATION_STATE,
    MAX_GRANT_TTL_SECONDS,
    MAX_PHOTO_BYTES,
    MAX_PHOTOS,
    MAX_VIDEO_BYTES,
    MAX_VIDEO_DURATION_SECONDS,
    MAX_VIDEOS,
    MIN_PHOTOS,
    MIN_VIDEO_DURATION_SECONDS,
    SHARE_PROJECTION_FIELDS,
    AccessGrant,
    AssetState,
    CompletenessInput,
    MediaAsset,
    MediaKind,
    ModerationState,
    ProfileMediaRuleError,
    ShareConsent,
    UploadRequest,
    active_assets,
    assert_share_projection,
    assert_url_is_not_predictable,
    build_share_projection,
    compute_completeness,
    derive_asset_token,
    is_publishable,
    issue_access_grant,
    normalize_mbti,
    plan_delete,
    plan_replace,
    private_media_path,
    require_rejection_reason,
    validate_asset_transition,
    validate_moderation_transition,
    validate_upload,
    verify_access_grant,
)

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
SECRET = "unit-test-media-secret"
OWNER_ID = UUID(int=7)


def _uid(value: int) -> UUID:
    return UUID(int=value)


def _photo_request(**overrides: object) -> UploadRequest:
    kwargs: dict = {
        "kind": MediaKind.PHOTO,
        "mime_type": "image/jpeg",
        "byte_size": 500_000,
        "duration_seconds": None,
    }
    kwargs.update(overrides)
    return UploadRequest(**kwargs)  # type: ignore[arg-type]


def _video_request(**overrides: object) -> UploadRequest:
    kwargs: dict = {
        "kind": MediaKind.VIDEO,
        "mime_type": "video/mp4",
        "byte_size": 5_000_000,
        "duration_seconds": 12.0,
    }
    kwargs.update(overrides)
    return UploadRequest(**kwargs)  # type: ignore[arg-type]


def _asset(
    index: int,
    *,
    kind: MediaKind = MediaKind.PHOTO,
    state: AssetState = AssetState.ACTIVE,
    moderation: ModerationState = ModerationState.APPROVED,
    position: int = 1,
) -> MediaAsset:
    return MediaAsset(
        asset_id=_uid(index),
        kind=kind,
        state=state,
        moderation_state=moderation,
        position=position,
        mime_type="image/jpeg" if kind is MediaKind.PHOTO else "video/mp4",
        byte_size=500_000,
        access_token=derive_asset_token(_uid(index), secret=SECRET),
        duration_seconds=None if kind is MediaKind.PHOTO else 12.0,
    )


# ---------------------------------------------------------------------------
# PROFILE-001 phase-one counts, enforced server-side
# ---------------------------------------------------------------------------


def test_the_phase_one_limits_are_one_to_three_photos_and_one_video() -> None:
    assert (MIN_PHOTOS, MAX_PHOTOS, MAX_VIDEOS) == (1, 3, 1)


def test_a_first_photo_is_accepted() -> None:
    validate_upload(_photo_request(), existing_photo_count=0, existing_video_count=0)


def test_a_fourth_photo_is_rejected() -> None:
    with pytest.raises(ProfileMediaRuleError) as excinfo:
        validate_upload(_photo_request(), existing_photo_count=3, existing_video_count=0)
    assert excinfo.value.code == "MEDIA_PHOTO_LIMIT_REACHED"


def test_a_second_video_is_rejected() -> None:
    """Phase one allows exactly one video; the second upload must fail."""

    validate_upload(_video_request(), existing_photo_count=1, existing_video_count=0)
    with pytest.raises(ProfileMediaRuleError) as excinfo:
        validate_upload(_video_request(), existing_photo_count=1, existing_video_count=1)
    assert excinfo.value.code == "MEDIA_VIDEO_LIMIT_REACHED"
    assert excinfo.value.details["max_videos"] == 1


def test_replacing_the_single_video_is_allowed() -> None:
    """The slot being replaced does not count against the limit."""

    validate_upload(
        _video_request(),
        existing_photo_count=1,
        existing_video_count=1,
        replacing_asset_kind=MediaKind.VIDEO,
    )


# ---------------------------------------------------------------------------
# PROFILE-001 mime, size and duration, enforced server-side
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mime", ["image/gif", "image/svg+xml", "application/pdf", "text/html"])
def test_a_photo_mime_outside_the_allow_list_is_rejected(mime: str) -> None:
    with pytest.raises(ProfileMediaRuleError) as excinfo:
        validate_upload(
            _photo_request(mime_type=mime), existing_photo_count=0, existing_video_count=0
        )
    assert excinfo.value.code == "MEDIA_MIME_NOT_ALLOWED"


def test_a_video_mime_outside_the_allow_list_is_rejected() -> None:
    with pytest.raises(ProfileMediaRuleError) as excinfo:
        validate_upload(
            _video_request(mime_type="video/x-msvideo"),
            existing_photo_count=0,
            existing_video_count=0,
        )
    assert excinfo.value.code == "MEDIA_MIME_NOT_ALLOWED"


def test_a_photo_may_not_masquerade_as_a_video_mime() -> None:
    with pytest.raises(ProfileMediaRuleError):
        validate_upload(
            _photo_request(mime_type="video/mp4"),
            existing_photo_count=0,
            existing_video_count=0,
        )


def test_an_oversized_photo_is_rejected() -> None:
    with pytest.raises(ProfileMediaRuleError) as excinfo:
        validate_upload(
            _photo_request(byte_size=MAX_PHOTO_BYTES + 1),
            existing_photo_count=0,
            existing_video_count=0,
        )
    assert excinfo.value.code == "MEDIA_FILE_TOO_LARGE"


def test_an_oversized_video_is_rejected() -> None:
    with pytest.raises(ProfileMediaRuleError):
        validate_upload(
            _video_request(byte_size=MAX_VIDEO_BYTES + 1),
            existing_photo_count=0,
            existing_video_count=0,
        )


def test_an_empty_file_is_rejected() -> None:
    with pytest.raises(ProfileMediaRuleError) as excinfo:
        validate_upload(
            _photo_request(byte_size=0), existing_photo_count=0, existing_video_count=0
        )
    assert excinfo.value.code == "MEDIA_FILE_EMPTY"


def test_a_video_that_is_too_long_or_too_short_is_rejected() -> None:
    with pytest.raises(ProfileMediaRuleError) as excinfo:
        validate_upload(
            _video_request(duration_seconds=MAX_VIDEO_DURATION_SECONDS + 0.5),
            existing_photo_count=0,
            existing_video_count=0,
        )
    assert excinfo.value.code == "MEDIA_VIDEO_TOO_LONG"
    with pytest.raises(ProfileMediaRuleError) as excinfo:
        validate_upload(
            _video_request(duration_seconds=MIN_VIDEO_DURATION_SECONDS - 0.5),
            existing_photo_count=0,
            existing_video_count=0,
        )
    assert excinfo.value.code == "MEDIA_VIDEO_TOO_SHORT"


def test_an_unmeasurable_video_duration_is_rejected_rather_than_waved_through() -> None:
    with pytest.raises(ProfileMediaRuleError) as excinfo:
        validate_upload(
            _video_request(duration_seconds=None),
            existing_photo_count=0,
            existing_video_count=0,
        )
    assert excinfo.value.code == "MEDIA_VIDEO_DURATION_UNKNOWN"


def test_a_photo_carrying_a_duration_is_rejected() -> None:
    with pytest.raises(ProfileMediaRuleError) as excinfo:
        validate_upload(
            _photo_request(duration_seconds=5.0),
            existing_photo_count=0,
            existing_video_count=0,
        )
    assert excinfo.value.code == "MEDIA_DURATION_NOT_APPLICABLE"


# ---------------------------------------------------------------------------
# PROFILE-001 moderation is pending by default
# ---------------------------------------------------------------------------


def test_a_new_asset_starts_pending_and_is_not_publishable() -> None:
    assert DEFAULT_MODERATION_STATE is ModerationState.PENDING
    assert is_publishable("pending") is False
    assert is_publishable("rejected") is False
    assert is_publishable("withdrawn") is False
    assert is_publishable("approved") is True
    assert is_publishable("nonsense") is False


def test_the_moderation_state_machine_allows_review_and_re_review() -> None:
    validate_moderation_transition("pending", "approved")
    validate_moderation_transition("pending", "rejected")
    validate_moderation_transition("approved", "pending")
    validate_moderation_transition("rejected", "pending")


def test_a_rejected_asset_cannot_jump_straight_to_approved() -> None:
    with pytest.raises(ProfileMediaRuleError) as excinfo:
        validate_moderation_transition("rejected", "approved")
    assert excinfo.value.code == "MODERATION_TRANSITION_INVALID"


def test_a_withdrawn_asset_is_terminal() -> None:
    with pytest.raises(ProfileMediaRuleError):
        validate_moderation_transition("withdrawn", "approved")


def test_a_rejection_requires_a_machine_reason_code() -> None:
    assert require_rejection_reason(" nudity_detected ") == "nudity_detected"
    with pytest.raises(ProfileMediaRuleError) as excinfo:
        require_rejection_reason("  ")
    assert excinfo.value.code == "MODERATION_REASON_REQUIRED"
    with pytest.raises(ProfileMediaRuleError) as excinfo:
        require_rejection_reason("not a code!")
    assert excinfo.value.code == "MODERATION_REASON_INVALID"


# ---------------------------------------------------------------------------
# PROFILE-001 delete / replace lifecycle
# ---------------------------------------------------------------------------


def test_the_asset_lifecycle_is_explicit_and_deletion_is_terminal() -> None:
    validate_asset_transition("uploading", "active")
    validate_asset_transition("active", "replaced")
    validate_asset_transition("active", "deleted")
    with pytest.raises(ProfileMediaRuleError) as excinfo:
        validate_asset_transition("deleted", "active")
    assert excinfo.value.code == "ASSET_TRANSITION_INVALID"


def test_only_active_assets_occupy_a_slot() -> None:
    assets = [
        _asset(1, position=1),
        _asset(2, state=AssetState.REPLACED, position=1),
        _asset(3, state=AssetState.DELETED, position=2),
        _asset(4, kind=MediaKind.VIDEO, position=1),
    ]
    assert [item.asset_id for item in active_assets(assets, MediaKind.PHOTO)] == [_uid(1)]
    assert len(active_assets(assets)) == 2


def test_deleting_a_photo_reports_the_remaining_count() -> None:
    assets = [_asset(1, position=1), _asset(2, position=2)]
    plan = plan_delete(assets, asset_id=_uid(1))
    assert plan.target_state is AssetState.DELETED
    assert plan.remaining_photos == 1
    assert plan.profile_falls_below_minimum is False


def test_deleting_the_last_photo_of_a_published_profile_is_refused() -> None:
    assets = [_asset(1, position=1)]
    with pytest.raises(ProfileMediaRuleError) as excinfo:
        plan_delete(assets, asset_id=_uid(1), profile_is_published=True)
    assert excinfo.value.code == "MEDIA_MINIMUM_PHOTOS"
    # An unpublished profile may go empty; it just flags the shortfall.
    plan = plan_delete(assets, asset_id=_uid(1), profile_is_published=False)
    assert plan.profile_falls_below_minimum is True


def test_deleting_an_unknown_asset_is_an_error() -> None:
    with pytest.raises(ProfileMediaRuleError) as excinfo:
        plan_delete([_asset(1)], asset_id=_uid(99))
    assert excinfo.value.code == "ASSET_NOT_FOUND"


def test_replacing_keeps_the_slot_and_resets_moderation() -> None:
    """Carrying the old approval over would be a trivial moderation bypass."""

    assets = [_asset(1, position=2)]
    plan = plan_replace(assets, asset_id=_uid(1), request=_photo_request())
    assert plan.new_position == 2
    assert plan.new_moderation_state is ModerationState.PENDING
    assert plan.replaced_target_state is AssetState.REPLACED


def test_a_replacement_must_be_the_same_kind_of_media() -> None:
    assets = [_asset(1, position=1)]
    with pytest.raises(ProfileMediaRuleError) as excinfo:
        plan_replace(assets, asset_id=_uid(1), request=_video_request())
    assert excinfo.value.code == "MEDIA_REPLACE_KIND_MISMATCH"


def test_a_replacement_still_has_to_pass_the_upload_constraints() -> None:
    assets = [_asset(1, position=1)]
    with pytest.raises(ProfileMediaRuleError) as excinfo:
        plan_replace(
            assets, asset_id=_uid(1), request=_photo_request(byte_size=MAX_PHOTO_BYTES + 1)
        )
    assert excinfo.value.code == "MEDIA_FILE_TOO_LARGE"


# ---------------------------------------------------------------------------
# PROFILE-001 opaque tokens and short-lived grants
# ---------------------------------------------------------------------------


def test_the_asset_token_is_opaque_deterministic_and_key_scoped() -> None:
    token = derive_asset_token(_uid(1), secret=SECRET)
    assert len(token) == ASSET_TOKEN_LENGTH
    assert token == derive_asset_token(_uid(1), secret=SECRET)
    assert token != derive_asset_token(_uid(2), secret=SECRET)
    assert token != derive_asset_token(_uid(1), secret="rotated-secret")
    assert str(_uid(1)) not in token


def test_a_private_media_url_never_embeds_a_guessable_identifier() -> None:
    token = derive_asset_token(_uid(1), secret=SECRET)
    path = private_media_path(token)
    assert path == f"/media/private/{token}"
    assert_url_is_not_predictable(path, asset_id=_uid(1), owner_id=OWNER_ID)
    with pytest.raises(ProfileMediaRuleError) as excinfo:
        assert_url_is_not_predictable(
            f"/media/{_uid(1)}.jpg", asset_id=_uid(1), owner_id=OWNER_ID
        )
    assert excinfo.value.code == "MEDIA_URL_PREDICTABLE"
    with pytest.raises(ProfileMediaRuleError):
        assert_url_is_not_predictable(
            f"/media/users/{OWNER_ID}/1.jpg", asset_id=_uid(1), owner_id=OWNER_ID
        )


def test_a_malformed_token_is_rejected_before_it_reaches_storage() -> None:
    with pytest.raises(ProfileMediaRuleError) as excinfo:
        private_media_path("short")
    assert excinfo.value.code == "MEDIA_TOKEN_INVALID"


def test_a_grant_round_trips_for_the_right_viewer() -> None:
    token = derive_asset_token(_uid(1), secret=SECRET)
    grant = issue_access_grant(
        access_token=token, viewer_id=_uid(5), now=NOW, secret=SECRET
    )
    verify_access_grant(grant, viewer_id=_uid(5), now=NOW + timedelta(seconds=10), secret=SECRET)


def test_a_grant_is_bound_to_one_viewer() -> None:
    token = derive_asset_token(_uid(1), secret=SECRET)
    grant = issue_access_grant(
        access_token=token, viewer_id=_uid(5), now=NOW, secret=SECRET
    )
    with pytest.raises(ProfileMediaRuleError) as excinfo:
        verify_access_grant(grant, viewer_id=_uid(6), now=NOW, secret=SECRET)
    assert excinfo.value.code == "MEDIA_GRANT_WRONG_VIEWER"


def test_a_grant_expires() -> None:
    token = derive_asset_token(_uid(1), secret=SECRET)
    grant = issue_access_grant(
        access_token=token, viewer_id=_uid(5), now=NOW, secret=SECRET, ttl_seconds=60
    )
    with pytest.raises(ProfileMediaRuleError) as excinfo:
        verify_access_grant(
            grant, viewer_id=_uid(5), now=NOW + timedelta(seconds=61), secret=SECRET
        )
    assert excinfo.value.code == "MEDIA_GRANT_EXPIRED"


def test_a_forged_grant_signature_is_rejected() -> None:
    token = derive_asset_token(_uid(1), secret=SECRET)
    grant = issue_access_grant(
        access_token=token, viewer_id=_uid(5), now=NOW, secret=SECRET
    )
    forged = AccessGrant(
        access_token=grant.access_token,
        viewer_id=grant.viewer_id,
        expires_at=grant.expires_at + timedelta(days=365),
        signature=grant.signature,
    )
    with pytest.raises(ProfileMediaRuleError) as excinfo:
        verify_access_grant(forged, viewer_id=_uid(5), now=NOW, secret=SECRET)
    assert excinfo.value.code == "MEDIA_GRANT_SIGNATURE_INVALID"


def test_a_grant_may_not_outlive_the_configured_ceiling() -> None:
    with pytest.raises(ProfileMediaRuleError) as excinfo:
        issue_access_grant(
            access_token=derive_asset_token(_uid(1), secret=SECRET),
            viewer_id=_uid(5),
            now=NOW,
            secret=SECRET,
            ttl_seconds=MAX_GRANT_TTL_SECONDS + 1,
        )
    assert excinfo.value.code == "MEDIA_GRANT_TTL_INVALID"


# ---------------------------------------------------------------------------
# PROFILE-001 MBTI and completeness
# ---------------------------------------------------------------------------


def test_mbti_is_normalized_and_optional() -> None:
    assert normalize_mbti(" infj ") == "INFJ"
    assert normalize_mbti(None) is None
    assert normalize_mbti("   ") is None


def test_an_invented_mbti_type_is_rejected() -> None:
    with pytest.raises(ProfileMediaRuleError) as excinfo:
        normalize_mbti("XXXX")
    assert excinfo.value.code == "MBTI_TYPE_UNKNOWN"


def test_completeness_weights_total_one_hundred() -> None:
    assert sum(COMPLETENESS_WEIGHTS.values()) == 100


def test_an_empty_profile_scores_zero_and_lists_everything_as_missing() -> None:
    score = compute_completeness(CompletenessInput())
    assert score.percent == 0
    assert set(score.missing_codes) == set(COMPLETENESS_WEIGHTS)


def test_a_full_profile_scores_one_hundred() -> None:
    score = compute_completeness(
        CompletenessInput(
            approved_photo_count=3,
            has_approved_video=True,
            mbti="INFJ",
            intro_length=40,
            city_code="310000",
        )
    )
    assert score.percent == 100
    assert score.missing_codes == ()


def test_only_approved_media_earns_completeness_credit() -> None:
    """Pending uploads must not make the score jump and then fall back."""

    pending_only = compute_completeness(
        CompletenessInput(approved_photo_count=0, has_approved_video=False)
    )
    assert "photo_primary" in pending_only.missing_codes
    assert "video" in pending_only.missing_codes


def test_a_negative_photo_count_is_a_programming_error() -> None:
    with pytest.raises(ProfileMediaRuleError) as excinfo:
        compute_completeness(CompletenessInput(approved_photo_count=-1))
    assert excinfo.value.code == "COMPLETENESS_INPUT_INVALID"


# ---------------------------------------------------------------------------
# PROFILE-001 consent-scoped share projection
# ---------------------------------------------------------------------------


def test_sharing_is_off_by_default() -> None:
    consent = ShareConsent()
    assert consent.share_enabled is False
    assert consent.share_photos is False
    assert consent.share_video is False
    assert consent.share_mbti is False
    with pytest.raises(ProfileMediaRuleError) as excinfo:
        build_share_projection(
            user_id=OWNER_ID, display_name="Ada", consent=consent, assets=[]
        )
    assert excinfo.value.code == "PROFILE_SHARE_NOT_CONSENTED"


def test_the_share_projection_omits_fields_the_member_did_not_consent_to() -> None:
    payload = build_share_projection(
        user_id=OWNER_ID,
        display_name="Ada",
        consent=ShareConsent(share_enabled=True, share_photos=True),
        assets=[_asset(1), _asset(2, kind=MediaKind.VIDEO)],
        mbti="INFJ",
        intro="hello there friend",
        city_code="310000",
    )
    assert "photo_tokens" in payload
    # Omitted entirely rather than emitted as null, so nobody can infer that a
    # hidden video exists.
    assert "video_token" not in payload
    assert "mbti" not in payload
    assert "intro" not in payload
    assert "city_code" not in payload


def test_the_share_projection_excludes_unapproved_media() -> None:
    payload = build_share_projection(
        user_id=OWNER_ID,
        display_name="Ada",
        consent=ShareConsent(share_enabled=True, share_photos=True, share_video=True),
        assets=[
            _asset(1, moderation=ModerationState.PENDING),
            _asset(2, moderation=ModerationState.REJECTED, position=2),
            _asset(3, kind=MediaKind.VIDEO, moderation=ModerationState.PENDING),
        ],
    )
    assert "photo_tokens" not in payload
    assert "video_token" not in payload


def test_the_share_projection_includes_approved_and_consented_media_only() -> None:
    payload = build_share_projection(
        user_id=OWNER_ID,
        display_name="Ada",
        consent=ShareConsent(
            share_enabled=True,
            share_photos=True,
            share_video=True,
            share_mbti=True,
            share_intro=True,
            share_city=True,
        ),
        assets=[
            _asset(1, position=1),
            _asset(2, position=2, moderation=ModerationState.PENDING),
            _asset(3, kind=MediaKind.VIDEO, position=1),
        ],
        mbti="infj",
        intro="  hello there friend  ",
        city_code="310000",
        completeness_percent=85,
    )
    assert payload["photo_tokens"] == [_asset(1).access_token]
    assert payload["video_token"] == _asset(3, kind=MediaKind.VIDEO).access_token
    assert payload["mbti"] == "INFJ"
    assert payload["intro"] == "hello there friend"
    assert payload["city_code"] == "310000"
    assert payload["completeness_percent"] == 85
    assert set(payload) <= SHARE_PROJECTION_FIELDS
    assert_share_projection(payload)


def test_an_extra_field_in_a_share_projection_is_a_leak() -> None:
    payload = {"user_id": str(OWNER_ID), "phone_number": "13800000000"}
    with pytest.raises(ProfileMediaRuleError) as excinfo:
        assert_share_projection(payload)
    assert excinfo.value.code == "PROFILE_SHARE_PROJECTION_LEAK"
    assert excinfo.value.details["fields"] == ["phone_number"]
