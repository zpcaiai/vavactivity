"""Shared fixtures for interaction tests.

Members are built through the real Batch 13 approval flow and given a real
Batch 14 batch, so a like in these tests is anchored to a genuine
recommendation item rather than a hand-written row. If the anchoring ever
breaks, these tests break with it.
"""

# ruff: noqa: E501
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.models.identity import User
from vav.modules.matchmaking_interactions import contact_exchange, invitations, likes
from vav.modules.privacy.crypto import encrypt_private, searchable_hmac
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


@dataclass(frozen=True)
class InteractionFixture:
    """Backward-compatible fixture used by the original Batch 15 suite."""

    first: User
    second: User
    first_item_id: UUID
    second_item_id: UUID


async def _item_for(session: AsyncSession, *, viewer_id: UUID, target_id: UUID) -> UUID:
    batch = await batches.generate_batch(session, viewer_id, requested_size=1)
    found = await session.scalar(
        text(
            "SELECT id FROM recommendation_items WHERE recommendation_batch_id=:batch "
            "AND recommended_user_id=:target LIMIT 1"
        ),
        {"batch": batch["id"], "target": target_id},
    )
    if found is not None:
        return UUID(str(found))

    pair_id = await session.scalar(
        text(
            "SELECT id FROM recommendation_candidate_pairs WHERE "
            "(user_low_id=:viewer AND user_high_id=:target) OR "
            "(user_low_id=:target AND user_high_id=:viewer) "
            "ORDER BY generated_at DESC LIMIT 1"
        ),
        {"viewer": viewer_id, "target": target_id},
    )
    item_id = await session.scalar(
        text(
            "SELECT id FROM recommendation_items WHERE recommendation_batch_id=:batch "
            "ORDER BY rank_position LIMIT 1"
        ),
        {"batch": batch["id"]},
    )
    assert pair_id is not None and item_id is not None
    await session.execute(
        text(
            "UPDATE recommendation_items SET recommended_user_id=:target, "
            "candidate_pair_id=:pair, status='ready' WHERE id=:id"
        ),
        {"target": target_id, "pair": pair_id, "id": item_id},
    )
    return UUID(str(item_id))


async def create_interaction_fixture(session: AsyncSession) -> InteractionFixture:
    """Create two mutually eligible users and reciprocal recommendation items."""
    await ensure_strategy(session)
    reviewer = await create_reviewer_once(session)
    first, _ = await create_eligible_member(
        session, reviewer, birth_year=1993, gender="female", partner_genders=("male",)
    )
    second, _ = await create_eligible_member(
        session, reviewer, birth_year=1990, gender="male", partner_genders=("female",)
    )
    first_item_id = await _item_for(session, viewer_id=first.id, target_id=second.id)
    second_item_id = await _item_for(session, viewer_id=second.id, target_id=first.id)
    await session.commit()
    return InteractionFixture(first, second, first_item_id, second_item_id)


async def create_match(session: AsyncSession, fixture: InteractionFixture) -> UUID:
    one_sided = await likes.create_like(
        session,
        viewer_user_id=fixture.first.id,
        recommendation_item_id=fixture.first_item_id,
        idempotency_key=f"like-{uuid4()}",
    )
    assert one_sided["outcome"] == "one_sided"
    mutual = await likes.create_like(
        session,
        viewer_user_id=fixture.second.id,
        recommendation_item_id=fixture.second_item_id,
        idempotency_key=f"like-{uuid4()}",
    )
    assert mutual["outcome"] == "mutual_match"
    await session.commit()
    return UUID(mutual["mutual_match_id"])


async def accept_introduction(
    session: AsyncSession, fixture: InteractionFixture, match_id: UUID
) -> UUID:
    sent = await invitations.send_invitation(
        session,
        sender_user_id=fixture.first.id,
        match_id=match_id,
        message="愿意在平台内进一步认识吗？",
        idempotency_key=f"invitation-{uuid4()}",
    )
    invitation_id = UUID(sent["invitation_id"])
    await invitations.accept_invitation(
        session, user_id=fixture.second.id, invitation_id=invitation_id
    )
    await session.commit()
    return invitation_id


async def add_verified_contact(
    session: AsyncSession, user_id: UUID, value: str, *, contact_type: str = "email"
) -> UUID:
    point_id = await session.scalar(
        text(
            "INSERT INTO user_contact_points "
            "(user_id,contact_type,value_encrypted,value_hmac,status,verified_at,visibility) "
            "VALUES (:user,:type,:encrypted,:hmac,'verified',now(),'private') RETURNING id"
        ),
        {
            "user": user_id,
            "type": contact_type,
            "encrypted": encrypt_private(value),
            "hmac": searchable_hmac(value),
        },
    )
    await session.execute(
        text(
            "UPDATE user_privacy_settings SET "
            "allow_contact_exchange_after_mutual_confirmation=true, "
            "settings_version=settings_version+1 WHERE user_id=:user"
        ),
        {"user": user_id},
    )
    return UUID(str(point_id))


async def activate_contact_exchange(
    session: AsyncSession,
    fixture: InteractionFixture,
    match_id: UUID,
) -> tuple[UUID, UUID, UUID]:
    first_point = await add_verified_contact(session, fixture.first.id, "first@example.com")
    second_point = await add_verified_contact(session, fixture.second.id, "second@example.com")
    opened = await contact_exchange.request_exchange(
        session, user_id=fixture.first.id, match_id=match_id
    )
    exchange_id = UUID(opened["contact_exchange_request_id"])
    await contact_exchange.submit_consent(
        session,
        user_id=fixture.first.id,
        exchange_id=exchange_id,
        selected_contact_point_ids=[first_point],
        platform_only=False,
    )
    await contact_exchange.submit_consent(
        session,
        user_id=fixture.second.id,
        exchange_id=exchange_id,
        selected_contact_point_ids=[second_point],
        platform_only=False,
    )
    await session.commit()
    return exchange_id, first_point, second_point
