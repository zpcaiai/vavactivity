from uuid import uuid4

import pytest

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.models.content import TestimonialMetadata as StoryMetadata
from vav.models.identity import User
from vav.modules.content.domain import ContentEntryType, TranslationStatus
from vav.modules.content.schemas import LocalizationInput
from vav.modules.content.service import content_service
from vav.modules.identity.domain import UserStatus


@pytest.mark.asyncio
async def test_testimonial_cannot_publish_without_approved_consent() -> None:
    async with session_factory() as session:
        actor = User(
            id=uuid4(),
            email=f"story-editor-{uuid4()}@example.com",
            display_email="story-editor@example.com",
            password_hash=None,
            status=UserStatus.SUSPENDED,
        )
        session.add(actor)
        await session.commit()
        slug = f"story-{uuid4().hex}"
        entry = await content_service.create(
            session,
            entry_type=ContentEntryType.TESTIMONIAL,
            internal_name="Consent test",
            canonical_slug=slug,
            default_locale="zh-CN",
            localization=LocalizationInput(
                locale="zh-CN",
                localized_slug=slug,
                title="授权测试",
                content_blocks=[],
                translation_status=TranslationStatus.READY,
            ),
            change_summary="Create consent-test story",
            actor_id=actor.id,
        )
        session.add(
            StoryMetadata(
                entry_id=entry.id,
                consent_status="pending",
                anonymity_level="fully_anonymous",
            )
        )
        await session.commit()
        await content_service.transition(
            session,
            entry=entry,
            action="submit-review",
            actor_id=actor.id,
            reason="Review consent-test testimonial",
        )
        with pytest.raises(VavError) as error:
            await content_service.transition(
                session,
                entry=entry,
                action="publish",
                actor_id=actor.id,
                reason="Attempt publication without consent",
            )
        assert error.value.code == "TESTIMONIAL_CONSENT_REQUIRED"
