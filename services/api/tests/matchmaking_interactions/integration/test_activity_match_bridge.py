"""Post-event mutual choice joins the same interaction domain."""

# ruff: noqa: E501
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from vav.core.database import session_factory
from vav.modules.matchmaking_interactions import matches as match_service
from vav.modules.matchmaking_interactions.domain import InteractionSource, canonical_pair

from ..helpers import paired_members, reach_mutual_match


async def _activity_mutual_choice(session, user_a, user_b) -> UUID:
    """Build the Batch 6 rows this bridge consumes.

    Batch 6 owns producing these; here they are constructed directly so the
    test exercises the bridge itself rather than the activity workflow.
    """
    low, high = canonical_pair(user_a.id, user_b.id)
    activity_id = await session.scalar(
        text(
            "INSERT INTO activities (activity_code,internal_name,activity_format,default_locale,"
            "timezone,starts_at,ends_at,approval_policy,payment_timing_policy,created_by,updated_by) "
            "VALUES (:code,'bridge fixture','offline','zh-CN','Asia/Shanghai',"
            "now() - interval '2 days', now() - interval '1 day','automatic','before_confirmation',"
            ":actor,:actor) RETURNING id"
        ),
        {"code": f"ACT-{uuid4().hex[:10]}", "actor": low},
    )
    choices = []
    for chooser, chosen in ((low, high), (high, low)):
        choice_id = await session.scalar(
            text(
                "INSERT INTO activity_post_event_choices "
                "(activity_id,chooser_user_id,chosen_user_id,choice,submitted_at) "
                "VALUES (:activity,:chooser,:chosen,'interested',now()) RETURNING id"
            ),
            {"activity": activity_id, "chooser": chooser, "chosen": chosen},
        )
        choices.append(choice_id)
    choice_row = await session.scalar(
        text(
            "INSERT INTO activity_mutual_choices "
            "(activity_id,user_a_id,user_b_id,first_choice_id,second_choice_id,status,matched_at) "
            "VALUES (:activity,:low,:high,:first,:second,'matched',now()) RETURNING id"
        ),
        {
            "activity": activity_id,
            "low": low,
            "high": high,
            "first": choices[0],
            "second": choices[1],
        },
    )
    await session.commit()
    return UUID(str(choice_row))


@pytest.mark.asyncio
async def test_an_activity_choice_creates_a_unified_match() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        choice_id = await _activity_mutual_choice(session, viewer, candidate)

        match = await match_service.ingest_activity_mutual_choice(
            session, source_event_id=uuid4(), activity_mutual_choice_id=choice_id
        )
        await session.commit()
        assert match is not None
        assert match["source"] == InteractionSource.ACTIVITY_POST_EVENT.value


@pytest.mark.asyncio
async def test_replaying_the_same_event_creates_nothing_new() -> None:
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        choice_id = await _activity_mutual_choice(session, viewer, candidate)
        event_id = uuid4()

        first = await match_service.ingest_activity_mutual_choice(
            session, source_event_id=event_id, activity_mutual_choice_id=choice_id
        )
        await session.commit()
        second = await match_service.ingest_activity_mutual_choice(
            session, source_event_id=event_id, activity_mutual_choice_id=choice_id
        )
        await session.commit()

        assert first is not None
        # A replay is a no-op, not an error and not a second match.
        assert second is None
        low, high = canonical_pair(viewer.id, candidate.id)
        count = await session.scalar(
            text(
                "SELECT count(*) FROM matchmaking_mutual_matches "
                "WHERE user_low_id=:low AND user_high_id=:high"
            ),
            {"low": low, "high": high},
        )
        assert int(count or 0) == 1


@pytest.mark.asyncio
async def test_an_activity_choice_attaches_to_an_existing_recommendation_match() -> None:
    """One pair, one current match, two recorded sources."""
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        existing = await reach_mutual_match(session, viewer, candidate)
        choice_id = await _activity_mutual_choice(session, viewer, candidate)

        match = await match_service.ingest_activity_mutual_choice(
            session, source_event_id=uuid4(), activity_mutual_choice_id=choice_id
        )
        await session.commit()
        assert match is not None
        assert match["id"] == existing["id"]

        sources = await session.scalar(
            text("SELECT count(*) FROM matchmaking_match_sources WHERE mutual_match_id=:id"),
            {"id": existing["id"]},
        )
        assert int(sources or 0) >= 2


@pytest.mark.asyncio
async def test_an_unmatched_activity_choice_is_refused_and_dead_lettered() -> None:
    """A fabricated or half-finished choice does not become a match."""
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        choice_id = await _activity_mutual_choice(session, viewer, candidate)
        await session.execute(
            text("UPDATE activity_mutual_choices SET status='pending' WHERE id=:id"),
            {"id": choice_id},
        )
        await session.commit()

        event_id = uuid4()
        result = await match_service.ingest_activity_mutual_choice(
            session, source_event_id=event_id, activity_mutual_choice_id=choice_id
        )
        await session.commit()
        assert result is None

        dead = await session.scalar(
            text(
                "SELECT count(*) FROM matchmaking_interaction_dead_letters d "
                "JOIN matchmaking_interaction_inbox_events e ON e.id = d.inbox_event_id "
                "WHERE e.source_event_id=:id"
            ),
            {"id": event_id},
        )
        assert int(dead or 0) == 1


@pytest.mark.asyncio
async def test_an_unknown_choice_reference_is_refused() -> None:
    async with session_factory() as session:
        result = await match_service.ingest_activity_mutual_choice(
            session, source_event_id=uuid4(), activity_mutual_choice_id=uuid4()
        )
        await session.commit()
        assert result is None


@pytest.mark.asyncio
async def test_an_activity_match_does_not_open_contact_details() -> None:
    """Meeting at an event is not consent to be contacted afterwards."""
    async with session_factory() as session:
        viewer, candidate = await paired_members(session)
        choice_id = await _activity_mutual_choice(session, viewer, candidate)
        match = await match_service.ingest_activity_mutual_choice(
            session, source_event_id=uuid4(), activity_mutual_choice_id=choice_id
        )
        await session.commit()
        assert match is not None

        grants = await session.scalar(
            text(
                "SELECT count(*) FROM matchmaking_contact_exchange_grants g "
                "JOIN matchmaking_contact_exchange_requests r ON r.id = g.contact_exchange_request_id "
                "WHERE r.mutual_match_id=:id"
            ),
            {"id": match["id"]},
        )
        assert int(grants or 0) == 0
