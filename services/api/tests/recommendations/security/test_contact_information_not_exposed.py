"""Recommendation output carries no contact detail or exact birth date."""

# ruff: noqa: E501
from __future__ import annotations

import pytest

from vav.core.database import session_factory
from vav.modules.recommendations import batches, service
from vav.modules.recommendations.batches import VISIBLE_SNAPSHOT_KEYS
from vav.modules.recommendations.domain import PROHIBITED_RECOMMENDATION_FIELDS

from ..helpers import create_eligible_member, create_reviewer_once, ensure_strategy


@pytest.mark.asyncio
async def test_items_never_carry_contact_details() -> None:
    async with session_factory() as session:
        await ensure_strategy(session)
        reviewer = await create_reviewer_once(session)
        viewer, _ = await create_eligible_member(
            session, reviewer, birth_year=1993, gender="female", partner_genders=("male",)
        )
        await create_eligible_member(
            session, reviewer, birth_year=1990, gender="male", partner_genders=("female",)
        )
        await batches.generate_batch(session, viewer.id)
        await session.commit()
        items = await batches.viewer_items(session, viewer_id=viewer.id)
        await session.commit()
        assert items

        for item in items:
            snapshot = item["visible_profile_snapshot"]
            assert set(snapshot) <= VISIBLE_SNAPSHOT_KEYS
            assert not set(snapshot) & PROHIBITED_RECOMMENDATION_FIELDS
            serialised = service.json_value(snapshot).lower()
            for marker in ("@", "wechat", "phone", "date_of_birth", "object_key", "street"):
                assert marker not in serialised


@pytest.mark.asyncio
async def test_an_unexpected_snapshot_field_fails_closed() -> None:
    from vav.common.exceptions import VavError

    with pytest.raises(VavError) as error:
        batches.assert_snapshot_is_safe({"display_name": "A", "email": "a@example.com"})
    assert error.value.code == "RECOMMENDATION_SNAPSHOT_FIELD_NOT_ALLOWED"
