"""Recommendation domain enums, states and non-negotiable policies.

The domain layer is pure so that eligibility, constraint, scoring and ranking
behaviour stays unit testable without a database.
"""

# ruff: noqa: E501

from __future__ import annotations

from enum import StrEnum
from uuid import UUID


class RecommendationBatchStatus(StrEnum):
    BUILDING = "building"
    VALIDATING = "validating"
    READY = "ready"
    ACTIVE = "active"
    EXHAUSTED = "exhausted"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    FAILED = "failed"


class RecommendationItemStatus(StrEnum):
    READY = "ready"
    EXPOSED = "exposed"
    VIEWED = "viewed"
    ACTED = "acted"
    SKIPPED = "skipped"
    WITHDRAWN = "withdrawn"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"


class CandidatePairStatus(StrEnum):
    ELIGIBLE = "eligible"
    HARD_CONSTRAINT_FAILED = "hard_constraint_failed"
    SAFETY_BLOCKED = "safety_blocked"
    PRIVACY_BLOCKED = "privacy_blocked"
    COOLDOWN = "cooldown"
    ALREADY_INTERACTED = "already_interacted"
    RANKED = "ranked"
    EXPOSED = "exposed"
    INVALIDATED = "invalidated"


class RecommendationExposureType(StrEnum):
    CARD_IMPRESSION = "card_impression"
    CARD_VISIBLE = "card_visible"
    PROFILE_OPENED = "profile_opened"
    PHOTO_VIEWED = "photo_viewed"


class RecommendationFeedbackType(StrEnum):
    IMPRESSION = "impression"
    VIEWED = "viewed"
    PROFILE_OPENED = "profile_opened"
    LIKED = "liked"
    SKIPPED = "skipped"
    NOT_RELEVANT = "not_relevant"
    WITHDRAWN = "withdrawn"
    MUTUAL_MATCHED = "mutual_matched"
    INTRODUCTION_ACCEPTED = "introduction_accepted"
    INTRODUCTION_DECLINED = "introduction_declined"
    RELATIONSHIP_STARTED = "relationship_started"
    RELATIONSHIP_ENDED = "relationship_ended"
    REPORTED = "reported"
    BLOCKED = "blocked"


class ColdStartType(StrEnum):
    NEW_USER = "new_user"
    NEW_PROFILE = "new_profile"
    SPARSE_PREFERENCES = "sparse_preferences"
    SPARSE_REGION = "sparse_region"
    NO_INTERACTION_HISTORY = "no_interaction_history"


class MissingnessPolicy(StrEnum):
    IGNORE_AND_LOWER_CONFIDENCE = "ignore_and_lower_confidence"
    NEUTRAL_SCORE = "neutral_score"
    CONFIGURED_PENALTY = "configured_penalty"


class ExplorationLevel(StrEnum):
    FOCUSED = "focused"
    BALANCED = "balanced"
    OPEN = "open"


BATCH_TRANSITIONS: dict[RecommendationBatchStatus, frozenset[RecommendationBatchStatus]] = {
    RecommendationBatchStatus.BUILDING: frozenset(
        {
            RecommendationBatchStatus.VALIDATING,
            RecommendationBatchStatus.FAILED,
            RecommendationBatchStatus.CANCELLED,
        }
    ),
    RecommendationBatchStatus.VALIDATING: frozenset(
        {
            RecommendationBatchStatus.READY,
            RecommendationBatchStatus.FAILED,
            RecommendationBatchStatus.CANCELLED,
        }
    ),
    RecommendationBatchStatus.READY: frozenset(
        {
            RecommendationBatchStatus.ACTIVE,
            RecommendationBatchStatus.CANCELLED,
            RecommendationBatchStatus.EXPIRED,
        }
    ),
    RecommendationBatchStatus.ACTIVE: frozenset(
        {
            RecommendationBatchStatus.EXHAUSTED,
            RecommendationBatchStatus.EXPIRED,
            RecommendationBatchStatus.CANCELLED,
        }
    ),
    RecommendationBatchStatus.EXHAUSTED: frozenset({RecommendationBatchStatus.EXPIRED}),
    RecommendationBatchStatus.EXPIRED: frozenset(),
    RecommendationBatchStatus.CANCELLED: frozenset(),
    RecommendationBatchStatus.FAILED: frozenset({RecommendationBatchStatus.CANCELLED}),
}


def can_transition_batch(current: str, target: str) -> bool:
    try:
        source = RecommendationBatchStatus(current)
        destination = RecommendationBatchStatus(target)
    except ValueError:
        return False
    return destination in BATCH_TRANSITIONS[source]


ITEM_TRANSITIONS: dict[RecommendationItemStatus, frozenset[RecommendationItemStatus]] = {
    RecommendationItemStatus.READY: frozenset(
        {
            RecommendationItemStatus.EXPOSED,
            RecommendationItemStatus.INVALIDATED,
            RecommendationItemStatus.EXPIRED,
        }
    ),
    RecommendationItemStatus.EXPOSED: frozenset(
        {
            RecommendationItemStatus.VIEWED,
            RecommendationItemStatus.SKIPPED,
            RecommendationItemStatus.ACTED,
            RecommendationItemStatus.INVALIDATED,
            RecommendationItemStatus.EXPIRED,
        }
    ),
    RecommendationItemStatus.VIEWED: frozenset(
        {
            RecommendationItemStatus.ACTED,
            RecommendationItemStatus.SKIPPED,
            RecommendationItemStatus.INVALIDATED,
            RecommendationItemStatus.EXPIRED,
        }
    ),
    RecommendationItemStatus.ACTED: frozenset(
        {RecommendationItemStatus.WITHDRAWN, RecommendationItemStatus.INVALIDATED}
    ),
    RecommendationItemStatus.SKIPPED: frozenset(
        {RecommendationItemStatus.WITHDRAWN, RecommendationItemStatus.INVALIDATED}
    ),
    RecommendationItemStatus.WITHDRAWN: frozenset({RecommendationItemStatus.INVALIDATED}),
    RecommendationItemStatus.INVALIDATED: frozenset(),
    RecommendationItemStatus.EXPIRED: frozenset(),
}


def can_transition_item(current: str, target: str) -> bool:
    try:
        source = RecommendationItemStatus(current)
        destination = RecommendationItemStatus(target)
    except ValueError:
        return False
    return destination in ITEM_TRANSITIONS[source]


def normalise_pair(user_a: UUID, user_b: UUID) -> tuple[UUID, UUID]:
    """Return a stable (low, high) ordering so a pair has exactly one record.

    Ordering never depends on which side asked for the recommendation.
    """
    if user_a == user_b:
        raise ValueError("a candidate pair requires two distinct users")
    return (user_a, user_b) if str(user_a) < str(user_b) else (user_b, user_a)


#: Reasons a member is not in the recommendation pool.
POOL_INELIGIBILITY_CODES: frozenset[str] = frozenset(
    {
        "account_not_active",
        "profile_not_active",
        "no_approved_version",
        "projection_not_eligible",
        "age_ineligible",
        "matchmaking_visibility_not_granted",
        "preferences_incomplete",
        "primary_photo_missing",
        "deletion_pending",
        "security_suspension",
        "recommendations_paused",
    }
)

#: Reasons a specific pair cannot be recommended.
PAIR_EXCLUSION_CODES: frozenset[str] = frozenset(
    {
        "same_user",
        "blocked",
        "safety_restricted",
        "relationship_in_progress",
        "interaction_in_progress",
        "skip_cooldown",
        "repeat_exposure_cooldown",
        "privacy_not_granted",
        "relationship_eligibility_mismatch",
        "hard_constraint_failed",
    }
)

#: Events that must invalidate affected candidates immediately.
CANDIDATE_INVALIDATION_EVENTS: frozenset[str] = frozenset(
    {
        "dating_profile.paused",
        "dating_profile.suspended",
        "dating_profile.privacy_updated",
        "dating_profile.preference_updated",
        "dating_profile.approved",
        "user.account.suspended",
        "moderation.block.created",
        "moderation.restriction.created",
        "matchmaking.relationship.started",
        "privacy.erasure.started",
    }
)

#: Signals that may never be turned into a score, by code or by an operator.
PROHIBITED_SCORING_SIGNALS: frozenset[str] = frozenset(
    {
        "photo_attractiveness",
        "facial_features",
        "skin_tone",
        "ethnicity_inference",
        "income_inference",
        "social_class_inference",
        "health_inference",
        "personality_diagnosis",
        "spiritual_maturity",
        "mental_health_status",
        "ai_conversation_content",
        "counseling_records",
        "payment_capacity",
        "spend_amount",
    }
)

#: Hard constraints the system may never relax, whatever the member allows.
NEVER_RELAXABLE_CONSTRAINTS: frozenset[str] = frozenset(
    {
        "adult_eligibility",
        "relationship_eligibility",
        "safety_block",
        "marital_status_explicit_rejection",
        "faith_requirement_user_locked",
    }
)

#: Feedback that must never be recycled as ordinary preference-learning data.
SAFETY_FEEDBACK_TYPES: frozenset[str] = frozenset({"blocked", "reported"})

SKIP_REASON_CODES: frozenset[str] = frozenset(
    {
        "location_not_suitable",
        "faith_expectations_differ",
        "relationship_goal_differs",
        "family_or_children_expectations_differ",
        "lifestyle_not_suitable",
        "profile_too_sparse",
        "not_looking_right_now",
        "prefer_not_to_say",
        "other",
    }
)

DOMAIN_EVENTS: tuple[str, ...] = (
    "recommendation.strategy.created",
    "recommendation.strategy.approved",
    "recommendation.strategy.activated",
    "recommendation.strategy.rolled_back",
    "recommendation.pool.user_added",
    "recommendation.pool.user_removed",
    "recommendation.candidates.generated",
    "recommendation.candidate.invalidated",
    "recommendation.hard_constraint.failed",
    "recommendation.score.generated",
    "recommendation.batch.generated",
    "recommendation.batch.activated",
    "recommendation.batch.invalidated",
    "recommendation.batch.expired",
    "recommendation.item.exposed",
    "recommendation.item.viewed",
    "recommendation.item.invalidated",
    "recommendation.feedback.received",
    "recommendation.user_tuning.updated",
    "recommendation.user_tuning.reset",
    "recommendation.experiment.started",
    "recommendation.experiment.stopped",
    "recommendation.evaluation.completed",
    "recommendation.release.blocked",
)

#: Guardrails that decide a release, not click-through or dwell time.
GUARDRAIL_METRICS: tuple[str, ...] = (
    "report_rate",
    "block_rate",
    "severe_negative_feedback_rate",
    "privacy_violation_rate",
    "hard_constraint_violation_rate",
    "safety_restriction_violation_rate",
    "exposure_imbalance",
    "empty_result_rate",
    "pool_exit_rate",
)
