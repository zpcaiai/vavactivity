"""Pure relationship journey rules.

Formal progress is mutual. A pause or ending is unilateral because nobody can
be required to remain in a relationship in order to protect a product metric.
"""

from __future__ import annotations

from enum import StrEnum


class JourneyStatus(StrEnum):
    PENDING_ACTIVATION = "pending_activation"
    ACTIVE = "active"
    PAUSED = "paused"
    SAFETY_FROZEN = "safety_frozen"
    ENDED = "ended"
    ARCHIVED = "archived"
    DELETION_PENDING = "deletion_pending"


class StageProposalStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"


class PauseStatus(StrEnum):
    ACTIVE = "active"
    RESUME_REQUESTED = "resume_requested"
    RESUMED = "resumed"
    ENDED = "ended"
    INVALIDATED = "invalidated"


STAGES = (
    "introduction_accepted",
    "initial_contact",
    "getting_to_know",
    "intentional_getting_to_know",
    "dating",
    "exclusive_relationship",
    "relationship_confirmed",
)


def validate_transition(current: str, proposed: str, *, allow_skip: bool = False) -> None:
    if current not in STAGES or proposed not in STAGES:
        raise ValueError("unknown relationship stage")
    current_index = STAGES.index(current)
    proposed_index = STAGES.index(proposed)
    if current_index == proposed_index:
        raise ValueError("stage is unchanged")
    if proposed_index > current_index + 1 and not allow_skip:
        raise ValueError("forward stage skipping is disabled")


def other_participant(*, user_low_id: object, user_high_id: object, actor_id: object) -> object:
    if actor_id == user_low_id:
        return user_high_id
    if actor_id == user_high_id:
        return user_low_id
    raise ValueError("actor is not a relationship participant")
