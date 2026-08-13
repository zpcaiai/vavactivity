"""The two editing consoles must share one revision sequence (CMS-001).

``content`` (the older console) and ``cms_publishing`` (the newer one) both
append to ``content_versions``. They used to disagree about what
``content_entries.current_version`` meant — an edit counter for one, the live
revision for the other — and that disagreement was not cosmetic: the older
console picked its next snapshot number from the counter, so once the newer
console had appended anything, the next save collided with a number that
already existed and the request failed with a unique-constraint violation.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text

from vav.core.database import session_factory
from vav.models.content import ContentEntry
from vav.models.identity import User
from vav.modules.content.domain import ContentEntryType
from vav.modules.content.schemas import LocalizationInput
from vav.modules.content.service import content_service
from vav.modules.identity.domain import UserStatus


async def _actor(session) -> User:
    actor = User(
        id=uuid4(),
        email=f"cms-seq-{uuid4().hex}@example.invalid",
        display_email="cms-seq@example.invalid",
        password_hash=None,
        status=UserStatus.SUSPENDED,
    )
    session.add(actor)
    await session.flush()
    return actor


async def _create_entry(session, actor: User, slug: str) -> ContentEntry:
    return await content_service.create(
        session,
        entry_type=ContentEntryType.PAGE,
        internal_name="Revision sequence probe",
        canonical_slug=slug,
        default_locale="zh-CN",
        localization=LocalizationInput(
            locale="zh-CN", localized_slug=slug, title="修订序列", content_blocks=[]
        ),
        change_summary="create",
        actor_id=actor.id,
    )


async def _append_foreign_revisions(session, entry_id: UUID, actor: User, count: int) -> int:
    """Append revisions the way ``cms_publishing`` does: straight to history.

    Written as raw inserts rather than through the CMS service so the test
    states the invariant — "another writer extended the history" — instead of
    depending on that module's feature flags being on.
    """

    head = int(
        await session.scalar(
            text("SELECT COALESCE(max(version_number),0) FROM content_versions WHERE entry_id=:e"),
            {"e": str(entry_id)},
        )
    )
    for offset in range(1, count + 1):
        await session.execute(
            text(
                "INSERT INTO content_versions "
                "  (entry_id,version_number,snapshot,change_summary,created_by) "
                "VALUES (:e,:n,'{}'::jsonb,'cms revision',:u)"
            ),
            {"e": str(entry_id), "n": head + offset, "u": str(actor.id)},
        )
    await session.execute(
        text("UPDATE content_entries SET current_version=:n WHERE id=:e"),
        {"n": head + count, "e": str(entry_id)},
    )
    await session.flush()
    return head + count


@pytest.mark.asyncio
async def test_legacy_console_save_survives_revisions_appended_elsewhere() -> None:
    slug = f"seq-{uuid4().hex}"
    async with session_factory() as session:
        actor = await _actor(session)
        entry = await _create_entry(session, actor, slug)

        head = await _append_foreign_revisions(session, entry.id, actor, count=2)

        # The save that used to raise UniqueViolationError.
        await content_service.update_localization(
            session,
            entry=entry,
            payload=LocalizationInput(
                locale="zh-CN", localized_slug=slug, title="修订序列 v2", content_blocks=[]
            ),
            expected_version=entry.version,
            change_summary="edit after foreign revisions",
            actor_id=actor.id,
        )

        numbers = list(
            (
                await session.scalars(
                    text(
                        "SELECT version_number FROM content_versions "
                        "WHERE entry_id=:e ORDER BY version_number"
                    ),
                    {"e": str(entry.id)},
                )
            ).all()
        )

    assert numbers == sorted(set(numbers)), "revision numbers must stay unique and ordered"
    assert numbers[-1] == head + 1, "the save must append past the foreign head, not reuse a number"


@pytest.mark.asyncio
async def test_current_version_tracks_the_head_of_history() -> None:
    slug = f"seq-{uuid4().hex}"
    async with session_factory() as session:
        actor = await _actor(session)
        entry = await _create_entry(session, actor, slug)
        await _append_foreign_revisions(session, entry.id, actor, count=3)
        await content_service.update_localization(
            session,
            entry=entry,
            payload=LocalizationInput(
                locale="zh-CN", localized_slug=slug, title="修订序列 v2", content_blocks=[]
            ),
            expected_version=entry.version,
            change_summary="edit",
            actor_id=actor.id,
        )

        row = (
            (
                await session.execute(
                    text(
                        "SELECT e.current_version, "
                        "  (SELECT max(v.version_number) FROM content_versions v "
                        "    WHERE v.entry_id=e.id) AS head "
                        "FROM content_entries e WHERE e.id=:e"
                    ),
                    {"e": str(entry.id)},
                )
            )
            .mappings()
            .first()
        )

    assert row is not None
    assert row["current_version"] == row["head"]


@pytest.mark.asyncio
async def test_published_revision_number_is_independent_of_the_head() -> None:
    """Publishing pins a revision; later drafts move the head, not the pin."""

    slug = f"seq-{uuid4().hex}"
    async with session_factory() as session:
        actor = await _actor(session)
        entry = await _create_entry(session, actor, slug)
        live = await _append_foreign_revisions(session, entry.id, actor, count=1)
        await session.execute(
            text(
                "UPDATE content_entries SET status='published',published_at=now(),"
                "published_revision_number=:live WHERE id=:e"
            ),
            {"live": live, "e": str(entry.id)},
        )
        await session.flush()

        head = await _append_foreign_revisions(session, entry.id, actor, count=2)
        await session.commit()

        row = (
            (
                await session.execute(
                    text(
                        "SELECT current_version,published_revision_number FROM content_entries "
                        "WHERE id=:e"
                    ),
                    {"e": str(entry.id)},
                )
            )
            .mappings()
            .first()
        )

    assert row is not None
    assert row["published_revision_number"] == live
    assert row["current_version"] == head
    assert row["current_version"] > row["published_revision_number"], (
        "unpublished drafts must be able to sit ahead of the live revision"
    )


@pytest.mark.asyncio
async def test_a_published_entry_cannot_lack_a_live_revision() -> None:
    """The database refuses the state that the old overloading hid."""

    slug = f"seq-{uuid4().hex}"
    async with session_factory() as session:
        actor = await _actor(session)
        entry = await _create_entry(session, actor, slug)
        await session.commit()
        entry_id = entry.id

    async with session_factory() as session:
        with pytest.raises(Exception) as error:
            await session.execute(
                text(
                    "UPDATE content_entries SET status='published',published_at=now() WHERE id=:e"
                ),
                {"e": str(entry_id)},
            )
            await session.commit()
        assert "published_revision_present" in str(error.value)
        await session.rollback()


@pytest.mark.asyncio
async def test_entry_row_still_reports_a_version_for_optimistic_locking() -> None:
    """``version`` is the edit lock and must stay untangled from the above."""

    slug = f"seq-{uuid4().hex}"
    async with session_factory() as session:
        actor = await _actor(session)
        entry = await _create_entry(session, actor, slug)
        before = entry.version
        await content_service.update_localization(
            session,
            entry=entry,
            payload=LocalizationInput(
                locale="zh-CN", localized_slug=slug, title="锁", content_blocks=[]
            ),
            expected_version=before,
            change_summary="edit",
            actor_id=actor.id,
        )
        refreshed = await session.scalar(select(ContentEntry).where(ContentEntry.id == entry.id))

    assert refreshed is not None
    assert refreshed.version == before + 1
