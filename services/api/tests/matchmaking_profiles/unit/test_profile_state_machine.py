"""Dating-profile, photo and review state machines."""

from __future__ import annotations

from vav.modules.matchmaking_profiles.domain import (
    PROFILE_TRANSITIONS,
    DatingPhotoStatus,
    DatingProfileStatus,
    ProfileReviewStatus,
    can_transition,
    can_transition_photo,
    can_transition_review,
)


def test_happy_path_lifecycle_is_reachable() -> None:
    path = [
        DatingProfileStatus.DRAFT,
        DatingProfileStatus.INCOMPLETE,
        DatingProfileStatus.READY_TO_SUBMIT,
        DatingProfileStatus.SUBMITTED,
        DatingProfileStatus.IN_REVIEW,
        DatingProfileStatus.APPROVED,
        DatingProfileStatus.ACTIVE,
    ]
    for current, target in zip(path, path[1:], strict=False):
        assert can_transition(current.value, target.value), f"{current} -> {target}"


def test_user_can_pause_and_resume() -> None:
    assert can_transition(
        DatingProfileStatus.ACTIVE.value, DatingProfileStatus.PAUSED_BY_USER.value
    )
    assert can_transition(
        DatingProfileStatus.PAUSED_BY_USER.value, DatingProfileStatus.ACTIVE.value
    )


def test_platform_can_suspend_active_profile() -> None:
    assert can_transition(DatingProfileStatus.ACTIVE.value, DatingProfileStatus.SUSPENDED.value)


def test_draft_cannot_jump_straight_to_active() -> None:
    assert not can_transition(DatingProfileStatus.DRAFT.value, DatingProfileStatus.ACTIVE.value)


def test_archived_is_terminal() -> None:
    assert PROFILE_TRANSITIONS[DatingProfileStatus.ARCHIVED] == frozenset()


def test_unknown_status_is_rejected() -> None:
    assert not can_transition("not_a_status", DatingProfileStatus.ACTIVE.value)


def test_rejected_photo_cannot_become_approved() -> None:
    assert not can_transition_photo(
        DatingPhotoStatus.REJECTED.value, DatingPhotoStatus.APPROVED.value
    )
    assert can_transition_photo(
        DatingPhotoStatus.REVIEW_REQUIRED.value, DatingPhotoStatus.APPROVED.value
    )


def test_review_cannot_be_decided_before_it_starts() -> None:
    assert not can_transition_review(
        ProfileReviewStatus.PENDING.value, ProfileReviewStatus.APPROVED.value
    )
    assert can_transition_review(
        ProfileReviewStatus.IN_REVIEW.value, ProfileReviewStatus.APPROVED.value
    )
