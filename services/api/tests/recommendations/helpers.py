"""Shared fixtures for recommendation tests.

Members are built through the real Batch 13 flow — complete profile, submit,
review approval, projection rebuild — so recommendation tests exercise the
production contract rather than hand-written projection rows.
"""

# ruff: noqa: E501
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.cli.seed_recommendations import seed_baseline_strategy, seed_features
from vav.models.identity import User
from vav.modules.matchmaking_profiles import service as profile_service
from vav.modules.recommendations import service as recommendation_service

from ..matchmaking_profiles.helpers import (
    create_complete_profile,
    create_member,
    create_reviewer,
    submit_and_approve,
)

#: A deterministic viewer projection used by the pure scoring tests.
BASE_PROJECTION: dict[str, Any] = {
    "age_years": 32,
    "age_bucket": "30_34",
    "country_code": "CN",
    "region_code": "east",
    "city_code": "shanghai",
    "gender_code": "female",
    "eligible_partner_gender_codes": ["male"],
    "faith_codes": ["believer_baptized", "reformed", "weekly", "marriage_faith_importance:5"],
    "relationship_intent": "marriage_oriented",
    "marital_status_code": "never_married",
    "children_status_code": "no_children",
    "relocation_willingness": "same_country",
    "language_codes": ["zh-CN", "en"],
    "lifestyle_codes": [
        "daily_schedule_code:standard",
        "smoking_status_code:never",
        "alcohol_use_code:never",
        "education_level_code:bachelor",
        "desire_children_code:want_children",
        "leisure_interest_codes:reading",
        "leisure_interest_codes:music",
        "communication_preference_codes:messaging",
    ],
    "indexed_preference_criteria": [],
}


def projection(**overrides: Any) -> dict[str, Any]:
    """Build a projection payload with the given overrides."""
    payload = {
        key: (list(value) if isinstance(value, list) else value)
        for key, value in BASE_PROJECTION.items()
    }
    payload.update(overrides)
    return payload


def criterion(
    code: str,
    operator: str,
    desired_value: Any,
    *,
    importance: str = "important",
    hard: bool = False,
    allow_unknown: bool = True,
    allow_system_relaxation: bool = False,
) -> dict[str, Any]:
    return {
        "criterion_code": code,
        "operator": operator,
        "desired_value": desired_value,
        "importance": importance,
        "hard_constraint": hard,
        "allow_unknown": allow_unknown,
        "allow_system_relaxation": allow_system_relaxation,
    }


async def ensure_strategy(session: AsyncSession) -> dict[str, Any]:
    """Make sure an active baseline strategy exists.

    A rollback test may leave the platform with no active strategy; the helper
    restores the most recent released version so later tests start from a
    known-good state.
    """
    existing = await session.scalar(
        text("SELECT count(*) FROM recommendation_strategies WHERE status='active'")
    )
    if not existing:
        await seed_features()
        restored = await session.scalar(
            text(
                "SELECT id FROM recommendation_strategies WHERE status IN ('superseded','rolled_back') "
                "ORDER BY activated_at DESC NULLS LAST LIMIT 1"
            )
        )
        if restored is not None:
            await session.execute(
                text(
                    "UPDATE recommendation_strategies SET status='active', activated_at=now() WHERE id=:id"
                ),
                {"id": restored},
            )
            await session.commit()
        else:
            await seed_baseline_strategy()
    return await recommendation_service.active_strategy(session)


async def create_eligible_member(
    session: AsyncSession,
    reviewer: User,
    *,
    birth_year: int = 1993,
    gender: str = "female",
    partner_genders: tuple[str, ...] = ("male",),
    city: str = "shanghai",
    criteria: list[dict[str, Any]] | None = None,
) -> tuple[User, dict[str, Any]]:
    """Create an approved, active, recommendation-eligible member."""
    user = await create_member(session, birth_year=birth_year)
    await create_complete_profile(session, user)
    await profile_service.update_fields(
        session,
        user,
        {
            "basic.gender_code": gender,
            "basic.eligible_partner_gender_codes": list(partner_genders),
            "location.city_code": city,
        },
    )
    if criteria is not None:
        await profile_service.replace_preferences(session, user, criteria, allow_relaxation=False)
    await session.commit()
    profile = await submit_and_approve(session, user, reviewer)
    await profile_service.rebuild_projection(session, profile["id"])
    entry = await recommendation_service.rebuild_pool_entry(session, user.id)
    await session.commit()
    assert entry is not None and entry["eligible"], entry
    return user, profile


async def create_reviewer_once(session: AsyncSession) -> User:
    return await create_reviewer(session, "profile_review_lead")


async def block_pair(session: AsyncSession, first: UUID, second: UUID) -> None:
    """Record an active interaction restriction between two members."""
    low, high = (first, second) if str(first) < str(second) else (second, first)
    await session.execute(
        text(
            "INSERT INTO activity_interaction_restrictions (user_a_id,user_b_id,status,reason_code) "
            "VALUES (:low,:high,'active','member_block') ON CONFLICT (user_a_id,user_b_id) "
            "DO UPDATE SET status='active'"
        ),
        {"low": low, "high": high},
    )
    await session.commit()
