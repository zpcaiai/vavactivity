"""Shared fixtures for interaction tests.

Members are built through the real Batch 13 approval flow and given a real
Batch 14 batch, so a like in these tests is anchored to a genuine
recommendation item rather than a hand-written row. If the anchoring ever
breaks, these tests break with it.
"""

# ruff: noqa: E501
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.models.identity import User
from vav.modules.recommendations import batches

from ..recommendations.helpers import (
    create_eligible_member,
    create_reviewer_once,
    criterion,
    ensure_strategy,
)


async def paired_members(
    session: AsyncSession, *, viewer_year: int = 1993, candidate_year: int = 1990
) -> tuple[User, User]:
    """Two approved members who are each other's only eligible candidate.

    The test database accumulates hundreds of approved members across runs, and
    a daily batch is capped well below that, so two ordinary members would
    rarely be recommended to each other. Giving each pair a private city and a
    hard city criterion on both sides makes the pairing deterministic without
    weakening any rule: the constraint engine still does the work, it just has
    exactly one candidate to find.
    """
    await ensure_strategy(session)
    reviewer = await create_reviewer_once(session)
    city = f"city-{uuid4().hex[:12]}"
    viewer, _ = await create_eligible_member(
        session,
        reviewer,
        birth_year=viewer_year,
        gender="female",
        partner_genders=("male",),
        city=city,
        criteria=[
            criterion(
                "city_code",
                "equals",
                city,
                importance="required",
                hard=True,
                allow_unknown=False,
            )
        ],
    )
    candidate, _ = await create_eligible_member(
        session,
        reviewer,
        birth_year=candidate_year,
        gender="male",
        partner_genders=("female",),
        city=city,
        criteria=[
            criterion(
                "city_code",
                "equals",
                city,
                importance="required",
                hard=True,
                allow_unknown=False,
            )
        ],
    )
    return viewer, candidate


async def recommendation_item_for(session: AsyncSession, *, viewer: User, candidate: User) -> UUID:
    """Generate a batch for the viewer and return the item pointing at candidate."""
    await batches.generate_batch(session, viewer.id)
    await session.commit()
    item_id = await session.scalar(
        text(
            "SELECT id FROM recommendation_items WHERE viewer_user_id=:viewer "
            "AND recommended_user_id=:candidate ORDER BY created_at DESC LIMIT 1"
        ),
        {"viewer": viewer.id, "candidate": candidate.id},
    )
    assert item_id is not None, "the candidate was not recommended to the viewer"
    return UUID(str(item_id))


async def mutual_items(session: AsyncSession, viewer: User, candidate: User) -> tuple[UUID, UUID]:
    """One recommendation item in each direction."""
    forward = await recommendation_item_for(session, viewer=viewer, candidate=candidate)
    backward = await recommendation_item_for(session, viewer=candidate, candidate=viewer)
    return forward, backward


def key() -> str:
    """A fresh idempotency key."""
    return str(uuid4())


async def verified_contact(
    session: AsyncSession, user: User, *, contact_type: str = "email", value: str | None = None
) -> UUID:
    """Give a member a verified contact point they can choose to share."""
    from vav.modules.privacy.crypto import encrypt_private, searchable_hmac

    plaintext = value or f"{user.id.hex[:10]}@contact.test"
    contact_id = await session.scalar(
        text(
            "INSERT INTO user_contact_points "
            "(user_id,contact_type,value_encrypted,value_hmac,status,verified_at) VALUES "
            "(:user,:type,:enc,:hmac,'verified',now()) "
            "ON CONFLICT (user_id,contact_type,value_hmac) DO UPDATE SET status='verified' "
            "RETURNING id"
        ),
        {
            "user": user.id,
            "type": contact_type,
            "enc": encrypt_private(plaintext),
            "hmac": searchable_hmac(plaintext),
        },
    )
    await session.commit()
    return UUID(str(contact_id))


async def allow_contact_exchange(session: AsyncSession, *users: User) -> None:
    """Turn on the Batch 12 privacy switch these members control."""
    for user in users:
        await session.execute(
            text(
                "INSERT INTO user_privacy_settings "
                "(user_id, allow_contact_exchange_after_mutual_confirmation) "
                "VALUES (:user, true) ON CONFLICT (user_id) DO UPDATE SET "
                "allow_contact_exchange_after_mutual_confirmation=true"
            ),
            {"user": user.id},
        )
    await session.commit()


async def reach_mutual_match(
    session: AsyncSession, viewer: User, candidate: User
) -> dict[str, Any]:
    """Both members like each other; return the resulting match row."""
    from vav.modules.matchmaking_interactions import likes as like_service

    forward, backward = await mutual_items(session, viewer, candidate)
    await like_service.create_like(
        session,
        viewer_user_id=viewer.id,
        recommendation_item_id=forward,
        idempotency_key=key(),
    )
    await session.commit()
    await like_service.create_like(
        session,
        viewer_user_id=candidate.id,
        recommendation_item_id=backward,
        idempotency_key=key(),
    )
    await session.commit()
    row = (
        await session.execute(
            text(
                "SELECT * FROM matchmaking_mutual_matches WHERE "
                "(user_low_id=:a AND user_high_id=:b) OR (user_low_id=:b AND user_high_id=:a)"
            ),
            {"a": viewer.id, "b": candidate.id},
        )
    ).mappings()
    match = row.first()
    assert match is not None, "the reciprocal likes did not create a match"
    return dict(match)


async def reach_accepted_introduction(
    session: AsyncSession, viewer: User, candidate: User
) -> dict[str, Any]:
    """Carry a pair all the way to an accepted introduction."""
    from vav.modules.matchmaking_interactions import invitations as invitation_service

    match = await reach_mutual_match(session, viewer, candidate)
    invitation = await invitation_service.send_invitation(
        session,
        sender_user_id=viewer.id,
        match_id=match["id"],
        message="I am glad we chose each other.",
        idempotency_key=key(),
    )
    await session.commit()
    await invitation_service.accept_invitation(
        session,
        user_id=candidate.id,
        invitation_id=UUID(invitation["invitation_id"]),
    )
    await session.commit()
    return {"match": match, "invitation_id": UUID(invitation["invitation_id"])}


async def outbox_topics(session: AsyncSession, *, topic: str) -> int:
    count = await session.scalar(
        text("SELECT count(*) FROM outbox_events WHERE topic=:topic"), {"topic": topic}
    )
    return int(count or 0)


async def block_pair(session: AsyncSession, first: UUID, second: UUID) -> None:
    """Record a block the way Batch 18 eventually will."""
    low, high = (first, second) if str(first) < str(second) else (second, first)
    await session.execute(
        text(
            "INSERT INTO recommendation_pair_exclusions "
            "(user_low_id,user_high_id,exclusion_type,source_module,reason_code) VALUES "
            "(:low,:high,'block','moderation','member_block') ON CONFLICT DO NOTHING"
        ),
        {"low": low, "high": high},
    )
    await session.commit()
