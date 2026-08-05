"""Gateways to the domains recommendations depend on but must not reach into.

Each gateway returns a decision, never another module's internal data. The
moderation gateway fails closed: if safety cannot be evaluated, the pair is not
recommended.
"""

# ruff: noqa: E501

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from vav.core.config import get_settings
from vav.modules.recommendations.domain import canonical_pair


@dataclass(frozen=True)
class RecommendationSafetyDecision:
    allowed: bool
    reason_code: str | None
    restriction_version: int
    valid_until: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason_code": self.reason_code,
            "restriction_version": self.restriction_version,
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
        }


class ModerationGateway:
    """Safety decisions for a candidate pair.

    Batch 18 will own reports, blocks and investigations. Until then this
    gateway reads the interaction restrictions Batch 6 already records and the
    exclusions other modules publish, and exposes only allow/deny.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def evaluate_recommendation_pair(
        self, *, viewer_user_id: UUID, candidate_user_id: UUID
    ) -> RecommendationSafetyDecision:
        settings = get_settings()
        low, high = canonical_pair(viewer_user_id, candidate_user_id)
        try:
            restriction = (
                await self._session.execute(
                    text(
                        "SELECT status, reason_code FROM activity_interaction_restrictions "
                        "WHERE user_a_id=:low AND user_b_id=:high"
                    ),
                    {"low": low, "high": high},
                )
            ).mappings()
            row = restriction.first()
            if row is not None and str(row["status"]) == "active":
                return RecommendationSafetyDecision(
                    allowed=False, reason_code="safety_restriction", restriction_version=1
                )

            suspended = (
                await self._session.execute(
                    text(
                        "SELECT count(*) FROM users WHERE id IN (:viewer,:candidate) "
                        "AND status <> 'active'"
                    ),
                    {"viewer": viewer_user_id, "candidate": candidate_user_id},
                )
            ).scalar_one()
            if int(suspended or 0) > 0:
                return RecommendationSafetyDecision(
                    allowed=False, reason_code="account_not_active", restriction_version=1
                )
        except SQLAlchemyError:
            if settings.recommendation_fail_closed_on_moderation_error:
                return RecommendationSafetyDecision(
                    allowed=False, reason_code="moderation_unavailable", restriction_version=0
                )
            raise
        return RecommendationSafetyDecision(allowed=True, reason_code=None, restriction_version=1)


class InteractionGateway:
    """Relationship, invitation and cooldown exclusions published by other batches.

    Batch 15 and Batch 16 write rows into ``recommendation_pair_exclusions``;
    Batch 14 only reads them so that interaction state stays owned elsewhere.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def excluded_partners(self, user_id: UUID, *, now: datetime) -> dict[str, str]:
        rows = (
            await self._session.execute(
                text(
                    "SELECT user_low_id, user_high_id, exclusion_type FROM recommendation_pair_exclusions "
                    "WHERE (user_low_id=:user_id OR user_high_id=:user_id) "
                    "AND (expires_at IS NULL OR expires_at > :now) AND released_at IS NULL"
                ),
                {"user_id": user_id, "now": now},
            )
        ).mappings()
        excluded: dict[str, str] = {}
        for row in rows:
            other = row["user_high_id"] if row["user_low_id"] == user_id else row["user_low_id"]
            excluded[str(other)] = str(row["exclusion_type"])
        return excluded


class ProfileGateway:
    """Read-only access to Batch 13 approved recommendation projections."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def projection(self, user_id: UUID) -> dict[str, Any] | None:
        row = (
            await self._session.execute(
                text(
                    "SELECT * FROM dating_profile_recommendation_projections WHERE user_id=:user_id"
                ),
                {"user_id": user_id},
            )
        ).mappings()
        found = row.first()
        return dict(found) if found is not None else None

    async def eligible_projections(
        self, *, exclude_user_id: UUID, limit: int
    ) -> list[dict[str, Any]]:
        rows = (
            await self._session.execute(
                text(
                    "SELECT * FROM dating_profile_recommendation_projections "
                    "WHERE eligible = true AND user_id <> :user_id "
                    "ORDER BY updated_at DESC LIMIT :limit"
                ),
                {"user_id": exclude_user_id, "limit": limit},
            )
        ).mappings()
        return [dict(row) for row in rows]


class MembershipGateway:
    """Membership effects on quantity only.

    Batch 17 owns entitlements. A membership may change how many
    recommendations a member receives; it can never bypass another member's
    conditions, safety rules or privacy settings.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def daily_received_limit(self, user_id: UUID, *, default_limit: int) -> int:
        return default_limit


class NotificationGateway:
    """Outbox handoff so notification delivery stays in Batch 11."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def queue_batch_ready(self, user_id: UUID, batch_id: UUID) -> None:
        await self._session.execute(
            text(
                "INSERT INTO outbox_events (topic,aggregate_type,aggregate_id,payload) "
                "VALUES ('recommendation.batch.activated','recommendation_batch',:batch_id,"
                "CAST(:payload AS jsonb))"
            ),
            {
                "batch_id": str(batch_id),
                "payload": f'{{"user_id": "{user_id}", "batch_id": "{batch_id}"}}',
            },
        )
