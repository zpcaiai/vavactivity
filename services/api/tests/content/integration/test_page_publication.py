from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from vav.core.database import session_factory
from vav.main import app
from vav.models.content import ContentEntry
from vav.modules.content.domain import ContentEntryType, TranslationStatus
from vav.modules.content.schemas import LocalizationInput
from vav.modules.content.service import content_service

SYSTEM_USER_ID = uuid4()


@pytest.mark.asyncio
async def test_page_create_review_publish_and_public_read() -> None:
    from vav.models.identity import User
    from vav.modules.identity.domain import UserStatus

    slug = f"test-page-{uuid4().hex}"
    async with session_factory() as session:
        actor = User(
            id=SYSTEM_USER_ID,
            email=f"cms-{uuid4()}@example.com",
            display_email="cms@example.com",
            password_hash=None,
            status=UserStatus.SUSPENDED,
        )
        session.add(actor)
        await session.commit()
        entry = await content_service.create(
            session,
            entry_type=ContentEntryType.PAGE,
            internal_name="Test page",
            canonical_slug=slug,
            default_locale="zh-CN",
            localization=LocalizationInput(
                locale="zh-CN",
                localized_slug=slug,
                title="测试页面",
                content_blocks=[],
            ),
            change_summary="Create integration-test page",
            actor_id=actor.id,
        )
        await content_service.update_localization(
            session,
            entry=entry,
            payload=LocalizationInput(
                locale="zh-CN",
                localized_slug=slug,
                title="测试页面",
                content_blocks=[],
                translation_status=TranslationStatus.READY,
            ),
            expected_version=entry.version,
            change_summary="Mark translation ready",
            actor_id=actor.id,
        )
        await content_service.transition(
            session,
            entry=entry,
            action="submit-review",
            actor_id=actor.id,
            reason="Integration test editorial review",
        )
        await content_service.transition(
            session,
            entry=entry,
            action="publish",
            actor_id=actor.id,
            reason="Integration test publication approval",
        )

    with TestClient(app) as client:
        response = client.get(f"/api/v1/public/content/pages/{slug}", params={"locale": "zh-CN"})
    assert response.status_code == 200
    assert response.json()["data"]["title"] == "测试页面"


@pytest.mark.asyncio
async def test_draft_page_is_not_public() -> None:
    async with session_factory() as session:
        entry = await session.scalar(
            select(ContentEntry)
            .where(ContentEntry.status == "draft")
            .order_by(ContentEntry.created_at.desc())
        )
        assert entry is not None
        slug = entry.canonical_slug

    with TestClient(app) as client:
        response = client.get(f"/api/v1/public/content/pages/{slug}", params={"locale": "zh-CN"})
    assert response.status_code == 404
