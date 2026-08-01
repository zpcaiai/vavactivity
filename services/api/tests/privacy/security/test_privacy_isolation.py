# ruff: noqa: E501
from __future__ import annotations

import pytest

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.core.database import session_factory
from vav.modules.privacy.service import (
    consume_export_download,
    create_request,
    ensure_privacy_defaults,
    issue_export_download_token,
    process_export_request,
)

from ..helpers import TEST_PASSWORD, create_privacy_user


@pytest.mark.asyncio
async def test_cross_user_export_token_is_rejected() -> None:
    async with session_factory() as session:
        owner = await create_privacy_user(session)
        other = await create_privacy_user(session)
        await ensure_privacy_defaults(session, owner)
        request_id = await create_request(
            session,
            user=owner,
            request_type="export",
            requested_scope={"modules": ["identity"]},
            requested_format="json",
            password=TEST_PASSWORD,
        )
        await process_export_request(session, request_id)
        token = await issue_export_download_token(session, owner.id, request_id)
        with pytest.raises(VavError) as error:
            await consume_export_download(session, other.id, token)
        assert error.value.code == "PRIVACY_EXPORT_TOKEN_INVALID"


def test_external_training_and_long_term_memory_default_off() -> None:
    settings = get_settings()
    assert settings.ai_external_training_default is False
    assert settings.ai_long_term_memory_default is False
    assert settings.ai_long_term_memory_opt_in_required is True
