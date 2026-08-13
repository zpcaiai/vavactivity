"""Public content API (B19 part 2).

Only published entries are reachable here, and an entry whose requested
translation is missing is served in the default locale with an explicit
``translation_fallback`` marker rather than silently in the wrong language.
"""

# ruff: noqa: B008, E501

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.schemas import success
from vav.core.request_context import request_id_from_request
from vav.modules.cms_publishing import service

router = APIRouter(prefix="/content")


@router.get("/entries")
async def list_entries(
    request: Request,
    content_type: str | None = Query(default=None, max_length=64),
    locale: str = Query(default="zh-CN", max_length=16),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await service.list_public_entries(
            session, content_type=content_type, locale=locale, limit=limit, offset=offset
        ),
        request_id_from_request(request),
    )


@router.get("/entries/{entry_code}")
async def read_entry(
    entry_code: str,
    request: Request,
    locale: str = Query(default="zh-CN", max_length=16),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Read one published entry.

    The response always names ``requested_locale`` and ``served_locale`` and
    carries ``translation_fallback``, so a client can label translated-by-
    fallback content instead of presenting it as the requested language.
    """

    return success(
        await service.read_public_entry(session, entry_code=entry_code, locale=locale),
        request_id_from_request(request),
    )


@router.get("/previews/{token}")
async def read_preview(
    token: str,
    request: Request,
    locale: str = Query(default="zh-CN", max_length=16),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Render an unpublished revision behind a time-boxed, revocable token.

    The token is matched by hash, so the stored row cannot be replayed into a
    working link.
    """

    return success(
        await service.read_preview(session, token=token, locale=locale),
        request_id_from_request(request),
    )
