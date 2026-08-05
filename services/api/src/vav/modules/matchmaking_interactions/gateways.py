"""Decisions from the domains interactions depend on but must not reach into.

Each gateway answers a question and returns a decision. None of them hand back
another module's rows, and the moderation gateway fails closed: if safety
cannot be evaluated, the interaction does not happen.
"""

# ruff: noqa: E501

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from vav.core.config import get_settings
from vav.modules.matchmaking_interactions.domain import canonical_pair


@dataclass(frozen=True)
class InteractionDecision:
    """Allowed or not, with a code the member is never shown directly."""

    allowed: bool
    reason_code: str | None = None
    restriction_version: int = 1

    @classmethod
    def allow(cls, *, restriction_version: int = 1) -> InteractionDecision:
        return cls(allowed=True, reason_code=None, restriction_version=restriction_version)

    @classmethod
    def deny(cls, reason_code: str, *, restriction_version: int = 1) -> InteractionDecision:
        return cls(allowed=False, reason_code=reason_code, restriction_version=restriction_version)


@dataclass(frozen=True)
class RecommendationItemContext:
    """What a like or skip must be anchored to."""

    item_id: UUID
    viewer_user_id: UUID
    recommended_user_id: UUID
    candidate_pair_id: UUID | None
    batch_id: UUID | None
    strategy_version: str | None
    status: str
    expires_at: datetime | None


class ModerationGateway:
    """Safety decisions for an interaction pair.

    Batch 18 will own reports, blocks and investigations. Until then this reads
    the restrictions Batch 6 already records plus the exclusions other modules
    publish, and exposes only allow/deny with an internal code.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def evaluate_pair(
        self, *, actor_user_id: UUID, target_user_id: UUID
    ) -> InteractionDecision:
        settings = get_settings()
        low, high = canonical_pair(actor_user_id, target_user_id)
        try:
            restriction = (
                await self._session.execute(
                    text(
                        "SELECT status FROM activity_interaction_restrictions "
                        "WHERE user_a_id=:low AND user_b_id=:high"
                    ),
                    {"low": low, "high": high},
                )
            ).mappings()
            row = restriction.first()
            if row is not None and str(row["status"]) == "active":
                return InteractionDecision.deny("restriction_created")

            exclusion = (
                await self._session.execute(
                    text(
                        "SELECT exclusion_type FROM recommendation_pair_exclusions "
                        "WHERE user_low_id=:low AND user_high_id=:high "
                        "AND released_at IS NULL "
                        "AND (expires_at IS NULL OR expires_at > now()) "
                        "AND exclusion_type IN ('block','safety','report')"
                    ),
                    {"low": low, "high": high},
                )
            ).mappings()
            blocked = exclusion.first()
            if blocked is not None:
                return InteractionDecision.deny("block_created")

            inactive = (
                await self._session.execute(
                    text(
                        "SELECT count(*) FROM users WHERE id IN (:actor,:target) "
                        "AND status <> 'active'"
                    ),
                    {"actor": actor_user_id, "target": target_user_id},
                )
            ).scalar_one()
            if int(inactive or 0) > 0:
                return InteractionDecision.deny("account_suspended")
        except SQLAlchemyError:
            if settings.matchmaking_fail_closed_on_moderation_error:
                return InteractionDecision.deny("moderation_unavailable", restriction_version=0)
            raise
        return InteractionDecision.allow()


class ProfileGateway:
    """Batch 13 profile status, read only."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    #: Only an ``active`` dating profile may take part in an interaction.
    #: Everything else — paused, suspended, archived, still in review — is a
    #: reason the member is not currently interacting, mapped to an internal
    #: code that never reaches the other side.
    _STATUS_REASONS = {
        "paused_by_user": "profile_paused",
        "suspended": "profile_suspended",
        "archived": "profile_archived",
        "deletion_pending": "erasure_started",
        "rejected": "profile_not_eligible",
    }

    async def interaction_status(self, user_id: UUID) -> InteractionDecision:
        row = (
            await self._session.execute(
                text(
                    "SELECT p.status AS profile_status, j.eligible "
                    "FROM dating_profiles p "
                    "LEFT JOIN dating_profile_recommendation_projections j "
                    "  ON j.user_id = p.user_id "
                    "WHERE p.user_id=:user_id"
                ),
                {"user_id": user_id},
            )
        ).mappings()
        profile = row.first()
        if profile is None:
            return InteractionDecision.deny("profile_not_published")
        status = str(profile["profile_status"])
        if status != "active":
            return InteractionDecision.deny(
                self._STATUS_REASONS.get(status, "profile_not_eligible")
            )
        if profile["eligible"] is None:
            return InteractionDecision.deny("profile_not_published")
        if not bool(profile["eligible"]):
            return InteractionDecision.deny("profile_not_eligible")
        return InteractionDecision.allow()


class PrivacyGateway:
    """Consent, erasure and contact points from Batch 12."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def erasure_in_progress(self, user_id: UUID) -> bool:
        try:
            pending = (
                await self._session.execute(
                    text(
                        "SELECT count(*) FROM privacy_erasure_plans "
                        "WHERE user_id=:user_id AND status IN ('planned','ready','processing')"
                    ),
                    {"user_id": user_id},
                )
            ).scalar_one()
        except SQLAlchemyError:
            # Fail closed: an unreadable erasure state must not permit new
            # interactions with a member who may be mid-deletion.
            return True
        return int(pending or 0) > 0

    async def allows_contact_exchange(self, user_id: UUID) -> bool:
        row = (
            await self._session.execute(
                text(
                    "SELECT allow_contact_exchange_after_mutual_confirmation "
                    "FROM user_privacy_settings WHERE user_id=:user_id"
                ),
                {"user_id": user_id},
            )
        ).mappings()
        settings_row = row.first()
        if settings_row is None:
            return False
        return bool(settings_row["allow_contact_exchange_after_mutual_confirmation"])

    async def verified_contact_points(self, user_id: UUID) -> list[dict[str, Any]]:
        """Only verified contact points can ever be selected for exchange."""
        rows = (
            await self._session.execute(
                text(
                    "SELECT id, contact_type, value_hmac, status, verified_at "
                    "FROM user_contact_points WHERE user_id=:user_id AND status='verified' "
                    "ORDER BY contact_type, created_at"
                ),
                {"user_id": user_id},
            )
        ).mappings()
        return [dict(row) for row in rows]

    async def contact_point(
        self, contact_point_id: UUID, *, owner_user_id: UUID
    ) -> dict[str, Any] | None:
        rows = (
            await self._session.execute(
                text(
                    "SELECT id, user_id, contact_type, value_encrypted, value_hmac, status "
                    "FROM user_contact_points WHERE id=:id AND user_id=:owner"
                ),
                {"id": contact_point_id, "owner": owner_user_id},
            )
        ).mappings()
        found = rows.first()
        return dict(found) if found is not None else None


class RecommendationGateway:
    """Batch 14 items, read only.

    Interactions never recompute a score and never read a preference document;
    they only confirm that an item is the viewer's, is current, and identifies
    which member it points at.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def item_context(
        self, item_id: UUID, *, viewer_user_id: UUID
    ) -> RecommendationItemContext | None:
        rows = (
            await self._session.execute(
                text(
                    "SELECT i.id, i.viewer_user_id, i.recommended_user_id, i.candidate_pair_id, "
                    "i.recommendation_batch_id, i.status, i.expires_at, "
                    "s.semantic_version AS strategy_version "
                    "FROM recommendation_items i "
                    "LEFT JOIN recommendation_batches b ON b.id = i.recommendation_batch_id "
                    "LEFT JOIN recommendation_strategies s ON s.id = b.strategy_id "
                    "WHERE i.id=:id AND i.viewer_user_id=:viewer"
                ),
                {"id": item_id, "viewer": viewer_user_id},
            )
        ).mappings()
        found = rows.first()
        if found is None:
            return None
        return RecommendationItemContext(
            item_id=found["id"],
            viewer_user_id=found["viewer_user_id"],
            recommended_user_id=found["recommended_user_id"],
            candidate_pair_id=found["candidate_pair_id"],
            batch_id=found["recommendation_batch_id"],
            strategy_version=found["strategy_version"],
            status=str(found["status"]),
            expires_at=found["expires_at"],
        )

    async def mark_item(self, item_id: UUID, *, status: str) -> None:
        await self._session.execute(
            text("UPDATE recommendation_items SET status=:status WHERE id=:id"),
            {"id": item_id, "status": status},
        )

    async def exclude_pair(
        self,
        *,
        user_low_id: UUID,
        user_high_id: UUID,
        exclusion_type: str,
        reason_code: str,
        expires_at: datetime | None,
    ) -> None:
        """Publish an exclusion so Batch 14 stops recommending the pair."""
        await self._session.execute(
            text(
                "INSERT INTO recommendation_pair_exclusions "
                "(user_low_id,user_high_id,exclusion_type,source_module,reason_code,expires_at) "
                "VALUES (:low,:high,:type,'matchmaking_interactions',:reason,:expires) "
                "ON CONFLICT DO NOTHING"
            ),
            {
                "low": user_low_id,
                "high": user_high_id,
                "type": exclusion_type,
                "reason": reason_code,
                "expires": expires_at,
            },
        )

    async def release_exclusion(
        self, *, user_low_id: UUID, user_high_id: UUID, exclusion_type: str
    ) -> None:
        await self._session.execute(
            text(
                "UPDATE recommendation_pair_exclusions SET released_at=now() "
                "WHERE user_low_id=:low AND user_high_id=:high AND exclusion_type=:type "
                "AND released_at IS NULL"
            ),
            {"low": user_low_id, "high": user_high_id, "type": exclusion_type},
        )


class RelationshipGateway:
    """Batch 16 relationship state.

    Batch 16 does not exist yet. Until it does, an accepted introduction is the
    only signal that a relationship has begun, and this gateway reads it from
    the invitations this module owns rather than inventing a placeholder table.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def has_active_relationship(self, *, user_a_id: UUID, user_b_id: UUID) -> bool:
        low, high = canonical_pair(user_a_id, user_b_id)
        started = (
            await self._session.execute(
                text(
                    "SELECT count(*) FROM matchmaking_mutual_matches "
                    "WHERE user_low_id=:low AND user_high_id=:high "
                    "AND status='introduction_accepted'"
                ),
                {"low": low, "high": high},
            )
        ).scalar_one()
        return int(started or 0) > 0


class ActivityGateway:
    """Post-event mutual choice from Batch 6."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def mutual_choice(self, choice_id: UUID) -> dict[str, Any] | None:
        try:
            rows = (
                await self._session.execute(
                    text(
                        "SELECT id, activity_id, user_a_id, user_b_id, status "
                        "FROM activity_mutual_choices WHERE id=:id"
                    ),
                    {"id": choice_id},
                )
            ).mappings()
        except SQLAlchemyError:
            return None
        found = rows.first()
        return dict(found) if found is not None else None


@dataclass
class OutboxEvent:
    topic: str
    aggregate_type: str
    aggregate_id: UUID
    payload: dict[str, Any] = field(default_factory=dict)


class EventGateway:
    """Outbox handoff.

    Notification delivery stays in Batch 11 and recommendation learning stays
    in Batch 14; this module only states what happened.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def publish(self, event: OutboxEvent) -> None:
        await self._session.execute(
            text(
                "INSERT INTO outbox_events (topic,aggregate_type,aggregate_id,payload) "
                "VALUES (:topic,:aggregate_type,:aggregate_id,CAST(:payload AS jsonb))"
            ),
            {
                "topic": event.topic,
                "aggregate_type": event.aggregate_type,
                "aggregate_id": str(event.aggregate_id),
                "payload": json.dumps(event.payload, default=str),
            },
        )

    async def publish_many(self, events: list[OutboxEvent]) -> None:
        for event in events:
            await self.publish(event)
