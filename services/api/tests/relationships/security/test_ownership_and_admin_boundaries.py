from pathlib import Path

import pytest

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.relationships import service

from ...matchmaking_interactions.helpers import create_interaction_fixture
from ..helpers import create_relationship_fixture


@pytest.mark.asyncio
async def test_third_party_cannot_read_or_change_journey() -> None:
    async with session_factory() as session:
        fixture = await create_relationship_fixture(session)
        outsider = await create_interaction_fixture(session)
        with pytest.raises(VavError) as denied:
            await service.get_journey(session, fixture.journey_id, outsider.first.id)
        assert denied.value.code == "RELATIONSHIP_NOT_FOUND"


def test_admin_router_cannot_confirm_member_decisions() -> None:
    source = (
        Path(__file__).parents[3] / "src/vav/modules/relationships/admin_router.py"
    ).read_text()
    assert "decide_stage_proposal" not in source
    assert "decide_resume" not in source
    assert "restore-ended" not in source
