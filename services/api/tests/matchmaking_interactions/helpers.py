"""Real Batch 13/14 fixtures for Batch 15 interaction tests."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vav.models.identity import User
from vav.modules.matchmaking_interactions import contact_exchange, invitations, likes
from vav.modules.privacy.crypto import encrypt_private, searchable_hmac
from vav.modules.recommendations import batches

from ..recommendations.helpers import create_eligible_member, create_reviewer_once, ensure_strategy


@dataclass(frozen=True)
class InteractionFixture:
    first: User
    second: User
    first_item_id: UUID
    second_item_id: UUID


async def _item_for(
    session: AsyncSession, *, viewer_id: UUID, target_id: UUID
) -> UUID:
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
