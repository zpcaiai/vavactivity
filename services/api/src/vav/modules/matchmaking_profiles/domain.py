"""Dating-profile domain enums, state machines and non-negotiable policies.

The domain layer is intentionally free of I/O so that state transitions,
eligibility rules and privacy classifications stay unit testable.
"""

# ruff: noqa: E501

from __future__ import annotations

from enum import StrEnum


class DatingProfileStatus(StrEnum):
    DRAFT = "draft"
    INCOMPLETE = "incomplete"
    READY_TO_SUBMIT = "ready_to_submit"
    SUBMITTED = "submitted"
    IN_REVIEW = "in_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    ACTIVE = "active"
    PAUSED_BY_USER = "paused_by_user"
    SUSPENDED = "suspended"
    REJECTED = "rejected"
    DELETION_PENDING = "deletion_pending"
    ARCHIVED = "archived"


class DatingPhotoStatus(StrEnum):
    UPLOADING = "uploading"
    PROCESSING = "processing"
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    REJECTED = "rejected"
    HIDDEN = "hidden"
    DELETED = "deleted"


class DatingPhotoRole(StrEnum):
    PRIMARY = "primary"
    GALLERY = "gallery"
    ACTIVITY = "activity"


class ProfileReviewStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_REVIEW = "in_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"


class ProfileReviewDecision(StrEnum):
    APPROVE = "approve"
    CHANGES_REQUIRED = "changes_required"
    REJECT = "reject"
    ESCALATE = "escalate"
    SUSPEND = "suspend"


class RelationshipIntent(StrEnum):
    MARRIAGE_ORIENTED = "marriage_oriented"
    SERIOUS_RELATIONSHIP = "serious_relationship"
    GETTING_TO_KNOW = "getting_to_know"
    UNDECIDED = "undecided"


class PreferenceImportance(StrEnum):
    REQUIRED = "required"
    VERY_IMPORTANT = "very_important"
    IMPORTANT = "important"
    NICE_TO_HAVE = "nice_to_have"
    NO_PREFERENCE = "no_preference"


class PreferenceOperator(StrEnum):
    EQUALS = "equals"
    IN = "in"
    RANGE = "range"
    AT_LEAST = "at_least"
    AT_MOST = "at_most"
    CONTAINS_ANY = "contains_any"
    CONTAINS_ALL = "contains_all"
    BOOLEAN = "boolean"


class DatingProfileViewContext(StrEnum):
    SELF = "self"
    ADMIN_REVIEW = "admin_review"
    RECOMMENDATION_CARD = "recommendation_card"
    PROFILE_DETAIL = "profile_detail"
    ACTIVITY_DIRECTORY = "activity_directory"
    MUTUAL_MATCH = "mutual_match"
    INTRODUCTION_ACCEPTED = "introduction_accepted"
    AI_CONTEXT = "ai_context"


class FieldSensitivity(StrEnum):
    CONTROLLED_PUBLIC = "controlled_public"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"
    HIGHLY_RESTRICTED = "highly_restricted"


# --------------------------------------------------------------------------
# Profile lifecycle
# --------------------------------------------------------------------------

PROFILE_TRANSITIONS: dict[DatingProfileStatus, frozenset[DatingProfileStatus]] = {
    DatingProfileStatus.DRAFT: frozenset(
        {
            DatingProfileStatus.INCOMPLETE,
            DatingProfileStatus.READY_TO_SUBMIT,
            DatingProfileStatus.DELETION_PENDING,
            DatingProfileStatus.ARCHIVED,
        }
    ),
    DatingProfileStatus.INCOMPLETE: frozenset(
        {
            DatingProfileStatus.DRAFT,
            DatingProfileStatus.READY_TO_SUBMIT,
            DatingProfileStatus.DELETION_PENDING,
            DatingProfileStatus.ARCHIVED,
        }
    ),
    DatingProfileStatus.READY_TO_SUBMIT: frozenset(
        {
            DatingProfileStatus.DRAFT,
            DatingProfileStatus.INCOMPLETE,
            DatingProfileStatus.SUBMITTED,
            DatingProfileStatus.DELETION_PENDING,
        }
    ),
    DatingProfileStatus.SUBMITTED: frozenset(
        {
            DatingProfileStatus.IN_REVIEW,
            DatingProfileStatus.CHANGES_REQUESTED,
            DatingProfileStatus.REJECTED,
            DatingProfileStatus.APPROVED,
            DatingProfileStatus.DELETION_PENDING,
        }
    ),
    DatingProfileStatus.IN_REVIEW: frozenset(
        {
            DatingProfileStatus.APPROVED,
            DatingProfileStatus.CHANGES_REQUESTED,
            DatingProfileStatus.REJECTED,
            DatingProfileStatus.SUSPENDED,
            DatingProfileStatus.DELETION_PENDING,
        }
    ),
    DatingProfileStatus.CHANGES_REQUESTED: frozenset(
        {
            DatingProfileStatus.DRAFT,
            DatingProfileStatus.INCOMPLETE,
            DatingProfileStatus.READY_TO_SUBMIT,
            DatingProfileStatus.DELETION_PENDING,
        }
    ),
    DatingProfileStatus.APPROVED: frozenset(
        {
            DatingProfileStatus.ACTIVE,
            DatingProfileStatus.SUSPENDED,
            DatingProfileStatus.DELETION_PENDING,
        }
    ),
    DatingProfileStatus.ACTIVE: frozenset(
        {
            DatingProfileStatus.PAUSED_BY_USER,
            DatingProfileStatus.SUSPENDED,
            DatingProfileStatus.DRAFT,
            DatingProfileStatus.READY_TO_SUBMIT,
            DatingProfileStatus.SUBMITTED,
            DatingProfileStatus.DELETION_PENDING,
        }
    ),
    DatingProfileStatus.PAUSED_BY_USER: frozenset(
        {
            DatingProfileStatus.ACTIVE,
            DatingProfileStatus.SUSPENDED,
            DatingProfileStatus.DELETION_PENDING,
        }
    ),
    DatingProfileStatus.SUSPENDED: frozenset(
        {
            DatingProfileStatus.ACTIVE,
            DatingProfileStatus.PAUSED_BY_USER,
            DatingProfileStatus.ARCHIVED,
            DatingProfileStatus.DELETION_PENDING,
        }
    ),
    DatingProfileStatus.REJECTED: frozenset(
        {
            DatingProfileStatus.DRAFT,
            DatingProfileStatus.INCOMPLETE,
            DatingProfileStatus.ARCHIVED,
            DatingProfileStatus.DELETION_PENDING,
        }
    ),
    DatingProfileStatus.DELETION_PENDING: frozenset({DatingProfileStatus.ARCHIVED}),
    DatingProfileStatus.ARCHIVED: frozenset(),
}

EDITABLE_STATUSES = frozenset(
    {
        DatingProfileStatus.DRAFT,
        DatingProfileStatus.INCOMPLETE,
        DatingProfileStatus.READY_TO_SUBMIT,
        DatingProfileStatus.CHANGES_REQUESTED,
        DatingProfileStatus.ACTIVE,
        DatingProfileStatus.PAUSED_BY_USER,
        DatingProfileStatus.SUBMITTED,
        DatingProfileStatus.IN_REVIEW,
    }
)

#: Statuses whose approved version may still be shown to other members.
DISPLAYABLE_STATUSES = frozenset({DatingProfileStatus.ACTIVE})


def can_transition(current: str, target: str) -> bool:
    try:
        source = DatingProfileStatus(current)
        destination = DatingProfileStatus(target)
    except ValueError:
        return False
    return destination in PROFILE_TRANSITIONS[source]


PHOTO_TRANSITIONS: dict[DatingPhotoStatus, frozenset[DatingPhotoStatus]] = {
    DatingPhotoStatus.UPLOADING: frozenset(
        {DatingPhotoStatus.PROCESSING, DatingPhotoStatus.DELETED}
    ),
    DatingPhotoStatus.PROCESSING: frozenset(
        {DatingPhotoStatus.REVIEW_REQUIRED, DatingPhotoStatus.REJECTED, DatingPhotoStatus.DELETED}
    ),
    DatingPhotoStatus.REVIEW_REQUIRED: frozenset(
        {DatingPhotoStatus.APPROVED, DatingPhotoStatus.REJECTED, DatingPhotoStatus.DELETED}
    ),
    DatingPhotoStatus.APPROVED: frozenset(
        {DatingPhotoStatus.HIDDEN, DatingPhotoStatus.REJECTED, DatingPhotoStatus.DELETED}
    ),
    DatingPhotoStatus.HIDDEN: frozenset({DatingPhotoStatus.APPROVED, DatingPhotoStatus.DELETED}),
    DatingPhotoStatus.REJECTED: frozenset({DatingPhotoStatus.DELETED}),
    DatingPhotoStatus.DELETED: frozenset(),
}


def can_transition_photo(current: str, target: str) -> bool:
    try:
        source = DatingPhotoStatus(current)
        destination = DatingPhotoStatus(target)
    except ValueError:
        return False
    return destination in PHOTO_TRANSITIONS[source]


REVIEW_TRANSITIONS: dict[ProfileReviewStatus, frozenset[ProfileReviewStatus]] = {
    ProfileReviewStatus.NOT_REQUIRED: frozenset({ProfileReviewStatus.PENDING}),
    ProfileReviewStatus.PENDING: frozenset(
        {ProfileReviewStatus.ASSIGNED, ProfileReviewStatus.IN_REVIEW}
    ),
    ProfileReviewStatus.ASSIGNED: frozenset(
        {ProfileReviewStatus.IN_REVIEW, ProfileReviewStatus.PENDING}
    ),
    ProfileReviewStatus.IN_REVIEW: frozenset(
        {
            ProfileReviewStatus.APPROVED,
            ProfileReviewStatus.CHANGES_REQUESTED,
            ProfileReviewStatus.REJECTED,
            ProfileReviewStatus.ESCALATED,
        }
    ),
    ProfileReviewStatus.ESCALATED: frozenset(
        {
            ProfileReviewStatus.APPROVED,
            ProfileReviewStatus.CHANGES_REQUESTED,
            ProfileReviewStatus.REJECTED,
            ProfileReviewStatus.IN_REVIEW,
        }
    ),
    ProfileReviewStatus.APPROVED: frozenset({ProfileReviewStatus.PENDING}),
    ProfileReviewStatus.CHANGES_REQUESTED: frozenset({ProfileReviewStatus.PENDING}),
    ProfileReviewStatus.REJECTED: frozenset({ProfileReviewStatus.PENDING}),
}


def can_transition_review(current: str, target: str) -> bool:
    try:
        source = ProfileReviewStatus(current)
        destination = ProfileReviewStatus(target)
    except ValueError:
        return False
    return destination in REVIEW_TRANSITIONS[source]


# --------------------------------------------------------------------------
# Sections and privacy classification
# --------------------------------------------------------------------------

PROFILE_SECTIONS: tuple[str, ...] = (
    "basic",
    "location",
    "faith",
    "relationship_history",
    "family",
    "children_and_parenting",
    "lifestyle",
    "education_and_work",
    "interests",
    "communication",
    "relationship_values",
    "self_introduction",
    "future_vision",
    "photos",
    "privacy",
)

#: Privacy data domains registered with the Batch 12 privacy control plane.
PRIVACY_DATA_DOMAINS: tuple[str, ...] = (
    "dating_profile.basic",
    "dating_profile.location",
    "dating_profile.faith",
    "dating_profile.relationship_history",
    "dating_profile.children",
    "dating_profile.family",
    "dating_profile.lifestyle",
    "dating_profile.narratives",
    "dating_profile.photos",
    "dating_profile.partner_preferences",
    "dating_profile.review_notes",
)

DOMAIN_SENSITIVITY: dict[str, FieldSensitivity] = {
    "dating_profile.basic": FieldSensitivity.CONTROLLED_PUBLIC,
    "dating_profile.location": FieldSensitivity.CONFIDENTIAL,
    "dating_profile.faith": FieldSensitivity.RESTRICTED,
    "dating_profile.relationship_history": FieldSensitivity.RESTRICTED,
    "dating_profile.children": FieldSensitivity.RESTRICTED,
    "dating_profile.family": FieldSensitivity.RESTRICTED,
    "dating_profile.lifestyle": FieldSensitivity.CONFIDENTIAL,
    "dating_profile.narratives": FieldSensitivity.CONTROLLED_PUBLIC,
    "dating_profile.photos": FieldSensitivity.RESTRICTED,
    "dating_profile.partner_preferences": FieldSensitivity.RESTRICTED,
    "dating_profile.review_notes": FieldSensitivity.HIGHLY_RESTRICTED,
}

#: Values that must never reach any viewer projection or recommendation index.
PROHIBITED_PROJECTION_FIELDS: frozenset[str] = frozenset(
    {
        "legal_name",
        "email",
        "phone",
        "wechat",
        "messaging_handle",
        "date_of_birth",
        "exact_address",
        "street_address",
        "self_introduction",
        "faith_journey",
        "marriage_vision",
        "family_vision",
        "narrative_full_text",
        "photo_object_key",
        "counseling_records",
        "ai_conversations",
        "payment_details",
        "review_internal_note",
        "security_incident_details",
    }
)

PHOTO_REJECTION_REASON_CODES: frozenset[str] = frozenset(
    {
        "photo_not_clear",
        "photo_not_personal",
        "photo_contains_contact_information",
        "photo_contains_third_party_without_basis",
        "photo_inappropriate_content",
        "photo_suspected_impersonation",
        "photo_duplicate",
        "photo_quality_too_low",
        "manual_review_required",
    }
)

DOMAIN_EVENTS: tuple[str, ...] = (
    "dating_profile.created",
    "dating_profile.updated",
    "dating_profile.version_created",
    "dating_profile.ready_to_submit",
    "dating_profile.submitted",
    "dating_profile.review_started",
    "dating_profile.changes_requested",
    "dating_profile.approved",
    "dating_profile.activated",
    "dating_profile.paused",
    "dating_profile.reactivated",
    "dating_profile.suspended",
    "dating_profile.restored",
    "dating_profile.archived",
    "dating_profile.photo.uploaded",
    "dating_profile.photo.processing_completed",
    "dating_profile.photo.approved",
    "dating_profile.photo.rejected",
    "dating_profile.photo.deleted",
    "dating_profile.primary_photo_changed",
    "dating_profile.preference.created",
    "dating_profile.preference.updated",
    "dating_profile.privacy_updated",
    "dating_profile.completeness_updated",
    "dating_profile.projection.updated",
    "dating_profile.projection.removed",
)

#: Events that must rebuild the recommendation projection.
PROJECTION_TRIGGER_EVENTS: frozenset[str] = frozenset(
    {
        "dating_profile.approved",
        "dating_profile.activated",
        "dating_profile.paused",
        "dating_profile.suspended",
        "dating_profile.privacy_updated",
        "dating_profile.preference_updated",
        "dating_profile.photo_approved",
        "dating_profile.age_eligibility_changed",
    }
)


def age_bucket(age_years: int | None) -> str | None:
    """Coarse age bucket used for exposure control and cold-start balancing."""
    if age_years is None:
        return None
    if age_years < 25:
        return "18_24"
    if age_years < 30:
        return "25_29"
    if age_years < 35:
        return "30_34"
    if age_years < 40:
        return "35_39"
    if age_years < 50:
        return "40_49"
    if age_years < 60:
        return "50_59"
    return "60_plus"
