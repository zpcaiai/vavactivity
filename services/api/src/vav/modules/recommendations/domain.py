"""Recommendation domain enums, state machines and non-negotiable policies.

The domain layer performs no I/O so that eligibility, constraint, scoring,
ranking, exposure and explanation rules stay unit testable and reproducible.
"""

# ruff: noqa: E501

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

# --------------------------------------------------------------------------
# States
# --------------------------------------------------------------------------


class RecommendationStrategyStatus(StrEnum):
    DRAFT = "draft"
    EVALUATING = "evaluating"
    APPROVED = "approved"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    ROLLED_BACK = "rolled_back"
    ARCHIVED = "archived"


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


class RecommendationBatchType(StrEnum):
    DAILY = "daily"
    SUPPLEMENTAL = "supplemental"
    MANUAL_REBUILD = "manual_rebuild"
    EVALUATION = "evaluation"


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
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    ADVENTUROUS = "adventurous"


class ExperimentStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"


class EvaluationRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


# --------------------------------------------------------------------------
# Transition tables
# --------------------------------------------------------------------------

STRATEGY_TRANSITIONS: dict[
    RecommendationStrategyStatus, frozenset[RecommendationStrategyStatus]
] = {
    RecommendationStrategyStatus.DRAFT: frozenset(
        {
            RecommendationStrategyStatus.EVALUATING,
            RecommendationStrategyStatus.ARCHIVED,
        }
    ),
    RecommendationStrategyStatus.EVALUATING: frozenset(
        {
            RecommendationStrategyStatus.DRAFT,
            RecommendationStrategyStatus.APPROVED,
            RecommendationStrategyStatus.ARCHIVED,
        }
    ),
    RecommendationStrategyStatus.APPROVED: frozenset(
        {
            RecommendationStrategyStatus.ACTIVE,
            RecommendationStrategyStatus.DRAFT,
            RecommendationStrategyStatus.ARCHIVED,
        }
    ),
    RecommendationStrategyStatus.ACTIVE: frozenset(
        {
            RecommendationStrategyStatus.SUPERSEDED,
            RecommendationStrategyStatus.ROLLED_BACK,
        }
    ),
    RecommendationStrategyStatus.SUPERSEDED: frozenset(
        {
            RecommendationStrategyStatus.ACTIVE,
            RecommendationStrategyStatus.ARCHIVED,
        }
    ),
    RecommendationStrategyStatus.ROLLED_BACK: frozenset(
        {
            RecommendationStrategyStatus.ARCHIVED,
            RecommendationStrategyStatus.DRAFT,
        }
    ),
    RecommendationStrategyStatus.ARCHIVED: frozenset(),
}

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
    RecommendationBatchStatus.EXHAUSTED: frozenset(
        {
            RecommendationBatchStatus.EXPIRED,
            RecommendationBatchStatus.CANCELLED,
        }
    ),
    RecommendationBatchStatus.EXPIRED: frozenset(),
    RecommendationBatchStatus.CANCELLED: frozenset(),
    RecommendationBatchStatus.FAILED: frozenset({RecommendationBatchStatus.CANCELLED}),
}

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
        {
            RecommendationItemStatus.WITHDRAWN,
            RecommendationItemStatus.INVALIDATED,
        }
    ),
    RecommendationItemStatus.SKIPPED: frozenset({RecommendationItemStatus.INVALIDATED}),
    RecommendationItemStatus.WITHDRAWN: frozenset({RecommendationItemStatus.INVALIDATED}),
    RecommendationItemStatus.INVALIDATED: frozenset(),
    RecommendationItemStatus.EXPIRED: frozenset(),
}


def can_transition_strategy(current: str, target: str) -> bool:
    try:
        source = RecommendationStrategyStatus(current)
        destination = RecommendationStrategyStatus(target)
    except ValueError:
        return False
    return destination in STRATEGY_TRANSITIONS[source]


def can_transition_batch(current: str, target: str) -> bool:
    try:
        source = RecommendationBatchStatus(current)
        destination = RecommendationBatchStatus(target)
    except ValueError:
        return False
    return destination in BATCH_TRANSITIONS[source]


def can_transition_item(current: str, target: str) -> bool:
    try:
        source = RecommendationItemStatus(current)
        destination = RecommendationItemStatus(target)
    except ValueError:
        return False
    return destination in ITEM_TRANSITIONS[source]


# --------------------------------------------------------------------------
# Canonical pair identity
# --------------------------------------------------------------------------


def canonical_pair(user_a: UUID, user_b: UUID) -> tuple[UUID, UUID]:
    """Return the stable ``(low, high)`` ordering for a candidate pair.

    Reversing the caller's argument order must never create a second pair,
    so ordering is derived from the identifiers themselves.
    """
    if user_a == user_b:
        raise ValueError("a candidate pair requires two different users")
    return (user_a, user_b) if str(user_a) < str(user_b) else (user_b, user_a)


def pair_direction(viewer_id: UUID, candidate_id: UUID) -> str:
    low, _high = canonical_pair(viewer_id, candidate_id)
    return "low_to_high" if viewer_id == low else "high_to_low"


# --------------------------------------------------------------------------
# Eligibility
# --------------------------------------------------------------------------

#: Pool-level eligibility reason codes, ordered from account to preference state.
POOL_INELIGIBILITY_CODES: tuple[str, ...] = (
    "account_not_active",
    "profile_not_active",
    "no_approved_version",
    "projection_not_eligible",
    "below_minimum_age",
    "age_unknown",
    "recommendation_paused_by_user",
    "recommendation_consent_missing",
    "security_suspension",
    "deletion_in_progress",
    "partner_preferences_incomplete",
)

#: Pair-level exclusion reason codes.
PAIR_EXCLUSION_CODES: tuple[str, ...] = (
    "same_user",
    "blocked_pair",
    "safety_restriction",
    "existing_relationship",
    "active_invitation",
    "skip_cooldown",
    "privacy_not_allowed",
    "relationship_eligibility_mismatch",
    "recent_exposure_cooldown",
    "hard_constraint_failed",
    "below_minimum_directional_score",
    "below_minimum_bidirectional_score",
    "daily_shown_limit_reached",
)

#: Events that immediately invalidate candidate pairs and unexposed items.
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

#: Safety rules that can never be relaxed, whatever the member allows.
NON_RELAXABLE_CRITERIA: frozenset[str] = frozenset(
    {
        "adult_eligibility",
        "relationship_eligibility",
        "safety_block",
        "safety_restriction",
        "privacy_consent",
    }
)

#: Criteria the platform evaluates as hard rules regardless of member settings.
PLATFORM_HARD_RULES: tuple[str, ...] = (
    "adult_eligibility",
    "relationship_eligibility",
)

#: Member criteria that may be enforced as hard constraints in v1.
SUPPORTED_HARD_CONSTRAINTS: tuple[str, ...] = (
    "relationship_eligibility",
    "age_range",
    "country_code",
    "region_code",
    "city_code",
    "relocation_willingness",
    "language_codes",
    "faith_status_code",
    "church_tradition_codes",
    "marital_status_code",
    "open_to_partner_with_children",
    "desire_children_code",
    "smoking_status_code",
    "relationship_intent",
)


# --------------------------------------------------------------------------
# Prohibited signals
# --------------------------------------------------------------------------

#: Inputs that must never become recommendation features, in any version.
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
        "spiritual_maturity_score",
        "mental_health_status",
        "ai_conversation_content",
        "counseling_records",
        "payment_capacity",
        "spend_amount",
    }
)

#: Values that must never appear in a recommendation DTO or explanation.
PROHIBITED_RECOMMENDATION_FIELDS: frozenset[str] = frozenset(
    {
        "legal_name",
        "email",
        "phone",
        "wechat",
        "messaging_handle",
        "date_of_birth",
        "exact_address",
        "street_address",
        "photo_object_key",
        "review_internal_note",
        "counseling_records",
        "ai_conversations",
        "payment_details",
        "partner_preference_criteria",
        "directional_score_of_other_user",
        "internal_feature_weights",
    }
)

#: Phrases the explanation layer must never produce.
PROHIBITED_EXPLANATION_PHRASES: tuple[str, ...] = (
    "soulmate",
    "guaranteed",
    "guarantee",
    "destined",
    "perfect match",
    "will marry",
    "probability of marriage",
    "灵魂伴侣",
    "保证",
    "命中注定",
    "百分百",
    "一定会",
)


# --------------------------------------------------------------------------
# Feedback policy
# --------------------------------------------------------------------------

#: Feedback that removes candidates immediately and is never learning data.
SAFETY_FEEDBACK_TYPES: frozenset[str] = frozenset(
    {
        RecommendationFeedbackType.REPORTED.value,
        RecommendationFeedbackType.BLOCKED.value,
    }
)

#: Feedback that starts a cooldown rather than a permanent exclusion.
COOLDOWN_FEEDBACK_TYPES: frozenset[str] = frozenset(
    {
        RecommendationFeedbackType.SKIPPED.value,
        RecommendationFeedbackType.NOT_RELEVANT.value,
        RecommendationFeedbackType.INTRODUCTION_DECLINED.value,
    }
)

#: Feedback types the recommendation module may accept from members directly.
MEMBER_FEEDBACK_TYPES: frozenset[str] = frozenset(
    {
        RecommendationFeedbackType.IMPRESSION.value,
        RecommendationFeedbackType.VIEWED.value,
        RecommendationFeedbackType.PROFILE_OPENED.value,
        RecommendationFeedbackType.NOT_RELEVANT.value,
    }
)

#: Feedback reason codes offered to members; details stay private.
FEEDBACK_REASON_CODES: tuple[str, ...] = (
    "location_not_suitable",
    "faith_expectations_differ",
    "relationship_goals_differ",
    "family_and_children_expectations_differ",
    "lifestyle_not_suitable",
    "profile_information_insufficient",
    "not_looking_right_now",
    "prefer_not_to_say",
    "other",
)


# --------------------------------------------------------------------------
# Audit and events
# --------------------------------------------------------------------------

AUDIT_EVENTS: tuple[str, ...] = (
    "recommendation.strategy.created",
    "recommendation.strategy.updated",
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
    "recommendation.experiment.created",
    "recommendation.experiment.approved",
    "recommendation.experiment.started",
    "recommendation.experiment.stopped",
    "recommendation.evaluation.started",
    "recommendation.evaluation.completed",
    "recommendation.release.blocked",
)

DOMAIN_EVENTS: tuple[str, ...] = (
    "recommendation.batch.activated",
    "recommendation.batch.invalidated",
    "recommendation.item.exposed",
    "recommendation.feedback.received",
    "recommendation.pool.updated",
)


# --------------------------------------------------------------------------
# Cache keys
# --------------------------------------------------------------------------


def pool_cache_key(pool_version: int) -> str:
    return f"recommendation:pool:{pool_version}"


def candidate_cache_key(
    user_id: UUID, profile_version: int, preference_version: int, strategy_version: str
) -> str:
    return f"recommendation:candidates:{user_id}:{profile_version}:{preference_version}:{strategy_version}"


def score_cache_key(pair_id: UUID, strategy_version: str, feature_version: str) -> str:
    return f"recommendation:score:{pair_id}:{strategy_version}:{feature_version}"


def batch_cache_key(user_id: UUID, batch_id: UUID, privacy_version: int) -> str:
    return f"recommendation:batch:{user_id}:{batch_id}:{privacy_version}"


def exposure_budget_cache_key(user_id: UUID, budget_date: str) -> str:
    return f"recommendation:exposure-budget:{user_id}:{budget_date}"


def explanation_cache_key(item_id: UUID, explanation_policy_version: str) -> str:
    return f"recommendation:explanation:{item_id}:{explanation_policy_version}"


#: Changes that invalidate every cached recommendation artefact for a member.
CACHE_INVALIDATION_TRIGGERS: frozenset[str] = frozenset(
    {
        "profile_approved",
        "preferences_changed",
        "privacy_changed",
        "recommendation_paused",
        "profile_paused",
        "block_created",
        "safety_restriction_changed",
        "relationship_state_changed",
        "strategy_rolled_back",
    }
)


# --------------------------------------------------------------------------
# Basis-point helpers
# --------------------------------------------------------------------------

BPS_MIN = 0
BPS_MAX = 10_000


def clamp_bps(value: int | float) -> int:
    """Clamp any score into the inclusive 0-10000 basis-point range."""
    return max(BPS_MIN, min(BPS_MAX, int(round(value))))
