from __future__ import annotations

import pytest

from vav.cli.seed_cms import SYSTEM_USER_ID
from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.notifications.service import (
    consume_unsubscribe_token,
    create_unsubscribe_token,
)


@pytest.mark.asyncio
async def test_marketing_unsubscribe_is_scoped_immediate_and_single_use() -> None:
    async with session_factory() as session:
        token = await create_unsubscribe_token(
            session, user_id=SYSTEM_USER_ID, category="marketing"
        )
        result = await consume_unsubscribe_token(session, token)
        assert result == {"status": "unsubscribed", "category": "marketing", "channel": "email"}
        with pytest.raises(VavError) as error:
            await consume_unsubscribe_token(session, token)
        assert error.value.code == "NOTIFICATION_UNSUBSCRIBE_TOKEN_INVALID"


@pytest.mark.asyncio
async def test_unsubscribe_token_cannot_disable_mandatory_category() -> None:
    async with session_factory() as session:
        with pytest.raises(VavError) as error:
            await create_unsubscribe_token(session, user_id=SYSTEM_USER_ID, category="security")
        assert error.value.code == "NOTIFICATION_UNSUBSCRIBE_CATEGORY_FORBIDDEN"
