# ruff: noqa: E501
from __future__ import annotations

import asyncio

import pytest

from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.privacy.service import create_request

from ..helpers import create_privacy_user


@pytest.mark.asyncio
async def test_only_one_active_request_per_user_and_type() -> None:
    async with session_factory() as session:
        user = await create_privacy_user(session)
        user_id = user.id

    async def submit() -> str:
        async with session_factory() as session:
            merged = await session.get(type(user), user_id)
            assert merged is not None
            try:
                await create_request(
                    session,
                    user=merged,
                    request_type="inventory",
                    requested_scope={"modules": "all"},
                )
                return "created"
            except VavError as error:
                return error.code

    results = await asyncio.gather(submit(), submit())
    assert sorted(results) == ["PRIVACY_REQUEST_ALREADY_ACTIVE", "created"]
