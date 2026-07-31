# ruff: noqa: B008

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.core.config import get_settings
from vav.models.content import ContentEntry, ContentLocalization
from vav.modules.content.domain import ContentEntryType, ContentStatus

seo_router = APIRouter(include_in_schema=False)


def _xml(urls: list[str]) -> Response:
    body = '<?xml version="1.0" encoding="UTF-8"?>\n'
    body += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    body += "".join(f"  <url><loc>{url}</loc></url>\n" for url in urls)
    body += "</urlset>\n"
    return Response(content=body, media_type="application/xml")


async def _published_urls(session: AsyncSession, entry_type: ContentEntryType) -> list[str]:
    rows = (
        await session.execute(
            select(ContentEntry, ContentLocalization)
            .join(
                ContentLocalization,
                ContentLocalization.entry_id == ContentEntry.id,
            )
            .where(
                ContentEntry.entry_type == entry_type,
                ContentEntry.status == ContentStatus.PUBLISHED,
                ContentEntry.visibility == "public",
                ContentLocalization.translation_status == "ready",
            )
            .order_by(ContentLocalization.locale, ContentEntry.canonical_slug)
        )
    ).all()
    base = get_settings().public_web_base_url.rstrip("/")
    prefix = (
        ""
        if entry_type == ContentEntryType.PAGE
        else "articles/"
        if entry_type == ContentEntryType.ARTICLE
        else "stories/"
    )
    return [
        f"{base}/{localized.locale}/{prefix}{localized.localized_slug or entry.canonical_slug}"
        for entry, localized in rows
    ]


@seo_router.get("/sitemap.xml")
async def sitemap_index() -> Response:
    base = get_settings().public_api_base_url.rstrip("/")
    body = '<?xml version="1.0" encoding="UTF-8"?>\n'
    body += '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    body += f"  <sitemap><loc>{base}/sitemaps/pages.xml</loc></sitemap>\n"
    body += f"  <sitemap><loc>{base}/sitemaps/articles.xml</loc></sitemap>\n"
    body += "</sitemapindex>\n"
    return Response(content=body, media_type="application/xml")


@seo_router.get("/sitemaps/pages.xml")
async def pages_sitemap(
    session: AsyncSession = Depends(get_database_session),
) -> Response:
    return _xml(await _published_urls(session, ContentEntryType.PAGE))


@seo_router.get("/sitemaps/articles.xml")
async def articles_sitemap(
    session: AsyncSession = Depends(get_database_session),
) -> Response:
    urls = await _published_urls(session, ContentEntryType.ARTICLE)
    urls.extend(await _published_urls(session, ContentEntryType.TESTIMONIAL))
    return _xml(urls)


@seo_router.get("/robots.txt")
async def robots() -> PlainTextResponse:
    settings = get_settings()
    base = settings.public_api_base_url.rstrip("/")
    if not settings.public_site_indexing_enabled:
        return PlainTextResponse("User-agent: *\nDisallow: /\n")
    return PlainTextResponse(f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n")
