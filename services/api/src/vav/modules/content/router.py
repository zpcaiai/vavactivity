# ruff: noqa: B008

from __future__ import annotations

import csv
import io
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from vav.api.dependencies import get_database_session
from vav.common.exceptions import VavError
from vav.common.schemas import success
from vav.core.config import get_settings
from vav.core.database import get_redis
from vav.core.request_context import request_id_from_request
from vav.models.content import (
    ArticleMetadata,
    ContactSubmission,
    ContentEntry,
    ContentLocalization,
    ContentPreviewToken,
    ContentVersion,
    MediaAsset,
    MediaAssetLocalization,
    NavigationItem,
    NavigationItemLocalization,
    NavigationMenu,
    SiteSetting,
    TestimonialMetadata,
)
from vav.modules.content.domain import ContentEntryType, ContentStatus
from vav.modules.content.media import media_service
from vav.modules.content.schemas import (
    ArticleCreateRequest,
    ContactAssignRequest,
    ContactResolveRequest,
    ContactStatusRequest,
    ContactSubmissionRequest,
    ContentCreateRequest,
    ContentUpdateRequest,
    LocalizationUpdateRequest,
    MediaCompleteRequest,
    MediaUpdateRequest,
    MediaUploadRequest,
    NavigationMenuUpdateRequest,
    PreviewTokenRequest,
    ReviewRequest,
    ScheduleRequest,
    SiteSettingRequest,
    TestimonialCreateRequest,
    VersionRestoreRequest,
)
from vav.modules.content.service import content_dict, content_service
from vav.modules.identity.abuse import enforce_rate_limit
from vav.modules.identity.audit import record_security_event
from vav.modules.identity.dependencies import (
    AuthenticatedPrincipal,
    request_fingerprint,
)
from vav.modules.identity.permissions import require_permission
from vav.modules.identity.security import privacy_hash, sha256_token

router = APIRouter()
SYSTEM_PAGE_SLOTS = {
    "home",
    "about",
    "services",
    "contact",
    "privacy",
    "terms",
    "refund-policy",
    "ai-disclaimer",
}
PROTECTED_PAGE_SLOTS = {"home", "privacy", "terms", "ai-disclaimer"}


async def _entry_payload(session: AsyncSession, entry: ContentEntry) -> dict[str, object]:
    localizations = list(
        (
            await session.scalars(
                select(ContentLocalization)
                .where(ContentLocalization.entry_id == entry.id)
                .order_by(ContentLocalization.locale)
            )
        ).all()
    )
    return content_dict(entry, localizations)


async def _public_entry(
    session: AsyncSession,
    *,
    entry_type: ContentEntryType,
    slug: str,
    locale: str,
) -> dict[str, object]:
    entry = await session.scalar(
        select(ContentEntry).where(
            ContentEntry.entry_type == entry_type,
            ContentEntry.canonical_slug == slug,
        )
    )
    if entry is None:
        raise VavError("CONTENT_NOT_FOUND", "Content was not found.", status_code=404)
    if entry.status == ContentStatus.PUBLISHED and entry.visibility == "public":
        payload = await _entry_payload(session, entry)
    else:
        version = await session.scalar(
            select(ContentVersion)
            .where(
                ContentVersion.entry_id == entry.id,
                ContentVersion.snapshot["status"].astext == ContentStatus.PUBLISHED,
            )
            .order_by(ContentVersion.version_number.desc())
            .limit(1)
        )
        if version is None:
            raise VavError("CONTENT_NOT_FOUND", "Content was not found.", status_code=404)
        payload = version.snapshot
    localizations = payload.get("localizations", {})
    if not isinstance(localizations, dict):
        raise VavError("CONTENT_NOT_FOUND", "Content was not found.", status_code=404)
    localized = localizations.get(locale)
    fallback_used = False
    if not isinstance(localized, dict) and get_settings().cms_allow_locale_fallback:
        localized = localizations.get(get_settings().cms_fallback_locale)
        fallback_used = True
    if not isinstance(localized, dict):
        raise VavError(
            "CONTENT_TRANSLATION_UNAVAILABLE",
            "Content translation is unavailable.",
            status_code=404,
        )
    localized = deepcopy(localized)
    blocks = localized.get("content_blocks")
    if isinstance(blocks, list):
        localized_locale = str(localized.get("locale") or locale)
        for block in blocks:
            if not isinstance(block, dict) or block.get("type") != "image":
                continue
            data = block.get("data")
            if not isinstance(data, dict) or not data.get("media_id"):
                continue
            try:
                media_id = UUID(str(data["media_id"]))
            except ValueError:
                continue
            metadata = await session.get(
                MediaAssetLocalization,
                (media_id, localized_locale),
            )
            data["alt_text"] = metadata.alt_text if metadata else ""
    return {
        "id": payload["id"],
        "entry_type": payload["entry_type"],
        "canonical_slug": payload["canonical_slug"],
        "published_at": payload.get("published_at"),
        "locale": localized.get("locale"),
        "fallback_used": fallback_used,
        **localized,
    }


@router.get("/public/content/pages/{slug}")
async def public_page(
    slug: str,
    request: Request,
    locale: str = Query(default="zh-CN"),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    payload = await _public_entry(
        session, entry_type=ContentEntryType.PAGE, slug=slug, locale=locale
    )
    return success(payload, request_id_from_request(request))


@router.get("/public/content/pages/{slug}/locales/{locale}")
async def public_page_locale(
    slug: str,
    locale: str,
    request: Request,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    payload = await _public_entry(
        session, entry_type=ContentEntryType.PAGE, slug=slug, locale=locale
    )
    return success(payload, request_id_from_request(request))


async def _public_list(
    session: AsyncSession,
    *,
    entry_type: ContentEntryType,
    locale: str,
    page: int,
    page_size: int,
) -> list[dict[str, object]]:
    entries = (
        await session.scalars(
            select(ContentEntry)
            .where(
                ContentEntry.entry_type == entry_type,
                ContentEntry.status == ContentStatus.PUBLISHED,
                ContentEntry.visibility == "public",
            )
            .order_by(ContentEntry.published_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    result: list[dict[str, object]] = []
    for entry in entries:
        try:
            result.append(
                await _public_entry(
                    session,
                    entry_type=entry_type,
                    slug=entry.canonical_slug,
                    locale=locale,
                )
            )
        except VavError as error:
            if error.code != "CONTENT_TRANSLATION_UNAVAILABLE":
                raise
    return result


@router.get("/public/articles")
async def public_articles(
    request: Request,
    locale: str = "zh-CN",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        {
            "items": await _public_list(
                session,
                entry_type=ContentEntryType.ARTICLE,
                locale=locale,
                page=page,
                page_size=page_size,
            )
        },
        request_id_from_request(request),
    )


@router.get("/public/articles/{slug}")
async def public_article(
    slug: str,
    request: Request,
    locale: str = "zh-CN",
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await _public_entry(session, entry_type=ContentEntryType.ARTICLE, slug=slug, locale=locale),
        request_id_from_request(request),
    )


@router.get("/public/testimonials")
async def public_testimonials(
    request: Request,
    locale: str = "zh-CN",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        {
            "items": await _public_list(
                session,
                entry_type=ContentEntryType.TESTIMONIAL,
                locale=locale,
                page=page,
                page_size=page_size,
            )
        },
        request_id_from_request(request),
    )


@router.get("/public/testimonials/{slug}")
async def public_testimonial(
    slug: str,
    request: Request,
    locale: str = "zh-CN",
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        await _public_entry(
            session,
            entry_type=ContentEntryType.TESTIMONIAL,
            slug=slug,
            locale=locale,
        ),
        request_id_from_request(request),
    )


async def _admin_list(
    session: AsyncSession,
    entry_type: ContentEntryType,
    page: int,
    page_size: int,
) -> list[dict[str, object]]:
    entries = (
        await session.scalars(
            select(ContentEntry)
            .where(ContentEntry.entry_type == entry_type)
            .order_by(ContentEntry.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return [await _entry_payload(session, entry) for entry in entries]


@router.get("/admin/content/pages")
async def admin_pages(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: AuthenticatedPrincipal = Depends(require_permission("content.pages.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        {"items": await _admin_list(session, ContentEntryType.PAGE, page, page_size)},
        request_id_from_request(request),
    )


@router.post("/admin/content/pages", status_code=201)
async def create_page(
    payload: ContentCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("content.pages.create")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    entry = await content_service.create(
        session,
        entry_type=ContentEntryType.PAGE,
        actor_id=principal.user.id,
        internal_name=payload.internal_name,
        canonical_slug=payload.canonical_slug,
        default_locale=payload.default_locale,
        localization=payload.localization,
        change_summary=payload.change_summary,
    )
    return success(await _entry_payload(session, entry), request_id_from_request(request))


@router.get("/admin/content/pages/{entry_id}")
async def get_page(
    entry_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("content.pages.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    entry = await session.get(ContentEntry, entry_id)
    if entry is None or entry.entry_type != ContentEntryType.PAGE:
        raise VavError("CONTENT_NOT_FOUND", "Content was not found.", status_code=404)
    return success(await _entry_payload(session, entry), request_id_from_request(request))


@router.patch("/admin/content/pages/{entry_id}")
async def update_page(
    entry_id: UUID,
    payload: ContentUpdateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("content.pages.update")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    entry = await session.get(ContentEntry, entry_id, with_for_update=True)
    if entry is None:
        raise VavError("CONTENT_NOT_FOUND", "Content was not found.", status_code=404)
    if entry.version != payload.expected_version:
        raise VavError(
            "CONTENT_VERSION_CONFLICT",
            "The content has been updated by another editor.",
            status_code=409,
        )
    if payload.internal_name is not None:
        entry.internal_name = payload.internal_name
    if payload.visibility is not None:
        entry.visibility = payload.visibility
    if entry.status == ContentStatus.PUBLISHED:
        entry.status = ContentStatus.DRAFT
    entry.version += 1
    entry.current_version += 1
    await session.flush()
    await content_service.snapshot(
        session,
        entry,
        actor_id=principal.user.id,
        change_summary=payload.change_summary,
    )
    await session.commit()
    return success(await _entry_payload(session, entry), request_id_from_request(request))


@router.put("/admin/content/pages/{entry_id}/localizations/{locale}")
async def update_page_localization(
    entry_id: UUID,
    locale: str,
    payload: LocalizationUpdateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("content.pages.update")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    if payload.locale != locale:
        raise VavError("LOCALE_MISMATCH", "Locale path and payload must match.")
    entry = await session.get(ContentEntry, entry_id, with_for_update=True)
    if entry is None:
        raise VavError("CONTENT_NOT_FOUND", "Content was not found.", status_code=404)
    expected_version = payload.expected_version
    change_summary = payload.change_summary
    localization_payload = payload.model_copy(update={}, deep=True)
    clean_payload = {
        key: value
        for key, value in localization_payload.model_dump().items()
        if key not in {"expected_version", "change_summary"}
    }
    from vav.modules.content.schemas import LocalizationInput

    await content_service.update_localization(
        session,
        entry=entry,
        payload=LocalizationInput.model_validate(clean_payload),
        expected_version=expected_version,
        change_summary=change_summary,
        actor_id=principal.user.id,
    )
    return success(await _entry_payload(session, entry), request_id_from_request(request))


async def _transition(
    entry_id: UUID,
    action: str,
    payload: ReviewRequest,
    request: Request,
    principal: AuthenticatedPrincipal,
    session: AsyncSession,
    expected_entry_type: ContentEntryType | None = None,
) -> dict[str, Any]:
    entry = await session.get(ContentEntry, entry_id, with_for_update=True)
    if entry is None or (
        expected_entry_type is not None and entry.entry_type != expected_entry_type
    ):
        raise VavError("CONTENT_NOT_FOUND", "Content was not found.", status_code=404)
    await content_service.transition(
        session,
        entry=entry,
        action=action,
        actor_id=principal.user.id,
        reason=payload.reason,
        scheduled_at=(
            payload.scheduled_publish_at if isinstance(payload, ScheduleRequest) else None
        ),
    )
    if action in {"publish", "approve", "archive", "restore"}:
        await get_redis().delete(f"cms:entry:{entry.id}")
    return success({"status": entry.status}, request_id_from_request(request))


def _transition_route(action: str, permission: str) -> Any:
    async def endpoint(
        entry_id: UUID,
        payload: ReviewRequest,
        request: Request,
        principal: AuthenticatedPrincipal = Depends(require_permission(permission)),
        session: AsyncSession = Depends(get_database_session),
    ) -> dict[str, Any]:
        return await _transition(entry_id, action, payload, request, principal, session)

    return endpoint


for action_name, permission_code in {
    "submit-review": "content.pages.update",
    "approve": "content.pages.review",
    "reject": "content.pages.review",
    "publish": "content.pages.publish",
    "archive": "content.pages.archive",
    "restore": "content.pages.update",
}.items():
    router.add_api_route(
        f"/admin/content/pages/{{entry_id}}/{action_name}",
        _transition_route(action_name, permission_code),
        methods=["POST"],
        name=f"content_page_{action_name.replace('-', '_')}",
    )


def _typed_transition_route(action: str, permission: str, entry_type: ContentEntryType) -> Any:
    async def endpoint(
        entry_id: UUID,
        payload: ReviewRequest,
        request: Request,
        principal: AuthenticatedPrincipal = Depends(require_permission(permission)),
        session: AsyncSession = Depends(get_database_session),
    ) -> dict[str, Any]:
        return await _transition(
            entry_id,
            action,
            payload,
            request,
            principal,
            session,
            expected_entry_type=entry_type,
        )

    return endpoint


for path_segment, entry_type, permission_prefix in (
    ("articles", ContentEntryType.ARTICLE, "content.articles"),
    ("testimonials", ContentEntryType.TESTIMONIAL, "content.testimonials"),
):
    for action_name, action_suffix in (
        ("submit-review", "update"),
        ("publish", "publish"),
        ("archive", "publish"),
        ("restore", "update"),
    ):
        router.add_api_route(
            f"/admin/content/{path_segment}/{{entry_id}}/{action_name}",
            _typed_transition_route(
                action_name,
                f"{permission_prefix}.{action_suffix}",
                entry_type,
            ),
            methods=["POST"],
            name=f"content_{path_segment}_{action_name.replace('-', '_')}",
        )


@router.delete("/admin/content/pages/{entry_id}")
async def delete_page(
    entry_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("content.pages.archive")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    entry = await session.get(ContentEntry, entry_id, with_for_update=True)
    if entry is None or entry.entry_type != ContentEntryType.PAGE:
        raise VavError("CONTENT_NOT_FOUND", "Content was not found.", status_code=404)
    if entry.canonical_slug in PROTECTED_PAGE_SLOTS:
        raise VavError(
            "PROTECTED_PAGE_CANNOT_BE_DELETED",
            "This required system page cannot be deleted.",
            status_code=409,
        )
    referenced = await session.scalar(
        select(NavigationItem.id).where(NavigationItem.target_entry_id == entry.id)
    )
    if referenced is not None:
        raise VavError(
            "CONTENT_IN_USE",
            "Content referenced by navigation cannot be deleted.",
            status_code=409,
        )
    entry.status = ContentStatus.ARCHIVED
    entry.archived_at = datetime.now(UTC)
    entry.version += 1
    record_security_event(
        session,
        event_type="content.entry.archived",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="content_entry",
        target_id=entry.id,
        reason="Page deleted through protected soft-delete workflow.",
    )
    await session.commit()
    return success({"status": "archived"}, request_id_from_request(request))


@router.post("/admin/content/pages/{entry_id}/schedule")
async def schedule_page(
    entry_id: UUID,
    payload: ScheduleRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("content.pages.publish")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _transition(entry_id, "schedule", payload, request, principal, session)


@router.get("/admin/content/pages/{entry_id}/versions")
async def content_versions(
    entry_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("content.pages.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    versions = (
        await session.scalars(
            select(ContentVersion)
            .where(ContentVersion.entry_id == entry_id)
            .order_by(ContentVersion.version_number.desc())
        )
    ).all()
    return success(
        {
            "items": [
                {
                    "version_number": version.version_number,
                    "change_summary": version.change_summary,
                    "created_by": str(version.created_by),
                    "created_at": version.created_at.isoformat(),
                }
                for version in versions
            ]
        },
        request_id_from_request(request),
    )


@router.post("/admin/content/pages/{entry_id}/versions/{version_number}/restore")
async def restore_content_version(
    entry_id: UUID,
    version_number: int,
    payload: VersionRestoreRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("content.pages.update")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    entry = await session.get(ContentEntry, entry_id, with_for_update=True)
    version = await session.scalar(
        select(ContentVersion).where(
            ContentVersion.entry_id == entry_id,
            ContentVersion.version_number == version_number,
        )
    )
    if entry is None or version is None:
        raise VavError(
            "CONTENT_VERSION_NOT_FOUND", "Content version was not found.", status_code=404
        )
    if entry.version != payload.expected_version:
        raise VavError("CONTENT_VERSION_CONFLICT", "The content has changed.", status_code=409)
    snapshot = version.snapshot
    entry.internal_name = str(snapshot["internal_name"])
    entry.visibility = str(snapshot["visibility"])
    entry.status = ContentStatus.DRAFT
    localizations = snapshot.get("localizations", {})
    if isinstance(localizations, dict):
        for locale, values in localizations.items():
            if not isinstance(values, dict):
                continue
            existing = await session.scalar(
                select(ContentLocalization).where(
                    ContentLocalization.entry_id == entry.id,
                    ContentLocalization.locale == locale,
                )
            )
            if existing is None:
                existing = ContentLocalization(
                    entry_id=entry.id, locale=locale, title=str(values.get("title", ""))
                )
                session.add(existing)
            for field, value in values.items():
                if field not in {"locale", "cover_media_id"} and hasattr(existing, field):
                    setattr(existing, field, value)
    entry.version += 1
    entry.current_version += 1
    await session.flush()
    await content_service.snapshot(
        session,
        entry,
        actor_id=principal.user.id,
        change_summary=f"Restore v{version_number}: {payload.reason}",
    )
    record_security_event(
        session,
        event_type="content.entry.version_restored",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="content_entry",
        target_id=entry.id,
        reason=payload.reason,
    )
    await session.commit()
    return success(await _entry_payload(session, entry), request_id_from_request(request))


@router.post("/admin/content/{entry_id}/preview-token")
async def create_preview_token(
    entry_id: UUID,
    payload: PreviewTokenRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("content.pages.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    raw_token = await content_service.create_preview_token(
        session,
        entry_id=entry_id,
        locale=payload.locale,
        actor_id=principal.user.id,
    )
    return success(
        {"token": raw_token, "expires_in": get_settings().cms_preview_token_ttl_minutes * 60},
        request_id_from_request(request),
    )


@router.get("/public/preview/{raw_token}")
async def preview_content(
    raw_token: str,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    token = await session.scalar(
        select(ContentPreviewToken).where(ContentPreviewToken.token_hash == sha256_token(raw_token))
    )
    if token is None or token.revoked_at is not None or token.expires_at <= datetime.now(UTC):
        raise VavError("PREVIEW_TOKEN_INVALID", "Preview token is invalid.", status_code=404)
    entry = await session.get(ContentEntry, token.entry_id)
    if entry is None:
        raise VavError("CONTENT_NOT_FOUND", "Content was not found.", status_code=404)
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    payload = await _entry_payload(session, entry)
    if token.locale:
        localizations = payload.get("localizations")
        if isinstance(localizations, dict):
            payload["localizations"] = {token.locale: localizations.get(token.locale)}
    return success(payload, request_id_from_request(request))


@router.get("/admin/content/articles")
async def admin_articles(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("content.articles.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        {"items": await _admin_list(session, ContentEntryType.ARTICLE, 1, 100)},
        request_id_from_request(request),
    )


@router.post("/admin/content/articles", status_code=201)
async def create_article(
    payload: ArticleCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("content.articles.create")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    entry = await content_service.create(
        session,
        entry_type=ContentEntryType.ARTICLE,
        actor_id=principal.user.id,
        internal_name=payload.internal_name,
        canonical_slug=payload.canonical_slug,
        default_locale=payload.default_locale,
        localization=payload.localization,
        change_summary=payload.change_summary,
    )
    session.add(ArticleMetadata(entry_id=entry.id, **payload.metadata.model_dump()))
    await session.commit()
    return success(await _entry_payload(session, entry), request_id_from_request(request))


async def _get_typed_entry(
    *,
    entry_id: UUID,
    entry_type: ContentEntryType,
    request: Request,
    session: AsyncSession,
) -> dict[str, Any]:
    entry = await session.get(ContentEntry, entry_id)
    if entry is None or entry.entry_type != entry_type:
        raise VavError("CONTENT_NOT_FOUND", "Content was not found.", status_code=404)
    return success(await _entry_payload(session, entry), request_id_from_request(request))


@router.get("/admin/content/articles/{entry_id}")
async def get_article(
    entry_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("content.articles.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _get_typed_entry(
        entry_id=entry_id,
        entry_type=ContentEntryType.ARTICLE,
        request=request,
        session=session,
    )


@router.patch("/admin/content/articles/{entry_id}")
async def update_article(
    entry_id: UUID,
    payload: ContentUpdateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("content.articles.update")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _update_typed_entry(
        entry_id=entry_id,
        entry_type=ContentEntryType.ARTICLE,
        payload=payload,
        request=request,
        principal=principal,
        session=session,
    )


@router.get("/admin/content/testimonials")
async def admin_testimonials(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("content.testimonials.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return success(
        {"items": await _admin_list(session, ContentEntryType.TESTIMONIAL, 1, 100)},
        request_id_from_request(request),
    )


@router.post("/admin/content/testimonials", status_code=201)
async def create_testimonial(
    payload: TestimonialCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("content.testimonials.create")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    entry = await content_service.create(
        session,
        entry_type=ContentEntryType.TESTIMONIAL,
        actor_id=principal.user.id,
        internal_name=payload.internal_name,
        canonical_slug=payload.canonical_slug,
        default_locale=payload.default_locale,
        localization=payload.localization,
        change_summary=payload.change_summary,
    )
    session.add(TestimonialMetadata(entry_id=entry.id, **payload.metadata.model_dump()))
    await session.commit()
    return success(await _entry_payload(session, entry), request_id_from_request(request))


async def _update_typed_entry(
    *,
    entry_id: UUID,
    entry_type: ContentEntryType,
    payload: ContentUpdateRequest,
    request: Request,
    principal: AuthenticatedPrincipal,
    session: AsyncSession,
) -> dict[str, Any]:
    entry = await session.scalar(
        select(ContentEntry).where(ContentEntry.id == entry_id).with_for_update()
    )
    if entry is None or entry.entry_type != entry_type:
        raise VavError("CONTENT_NOT_FOUND", "Content was not found.", status_code=404)
    if entry.version != payload.expected_version:
        raise VavError(
            "CONTENT_VERSION_CONFLICT",
            "The content has been updated by another editor.",
            status_code=409,
        )
    if payload.internal_name is not None:
        entry.internal_name = payload.internal_name
    if payload.visibility is not None:
        entry.visibility = payload.visibility
    if entry.status == ContentStatus.PUBLISHED:
        entry.status = ContentStatus.DRAFT
    entry.version += 1
    entry.current_version += 1
    await session.flush()
    await content_service.snapshot(
        session,
        entry,
        actor_id=principal.user.id,
        change_summary=payload.change_summary,
    )
    record_security_event(
        session,
        event_type="content.entry.updated",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="content_entry",
        target_id=entry.id,
        reason=payload.change_summary,
    )
    await session.commit()
    return success(await _entry_payload(session, entry), request_id_from_request(request))


@router.get("/admin/content/testimonials/{entry_id}")
async def get_testimonial(
    entry_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("content.testimonials.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _get_typed_entry(
        entry_id=entry_id,
        entry_type=ContentEntryType.TESTIMONIAL,
        request=request,
        session=session,
    )


@router.patch("/admin/content/testimonials/{entry_id}")
async def update_testimonial(
    entry_id: UUID,
    payload: ContentUpdateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("content.testimonials.update")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    return await _update_typed_entry(
        entry_id=entry_id,
        entry_type=ContentEntryType.TESTIMONIAL,
        payload=payload,
        request=request,
        principal=principal,
        session=session,
    )


@router.post("/admin/media/uploads", status_code=201)
async def create_media_upload(
    payload: MediaUploadRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("content.media.upload")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    asset, url = await media_service.create_upload(
        session, actor_id=principal.user.id, **payload.model_dump()
    )
    return success(
        {"id": str(asset.id), "upload_url": url, "object_key": None},
        request_id_from_request(request),
    )


@router.post("/admin/media/uploads/{asset_id}/complete")
async def complete_media_upload(
    asset_id: UUID,
    payload: MediaCompleteRequest,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("content.media.upload")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    asset = await session.get(MediaAsset, asset_id, with_for_update=True)
    if asset is None or asset.deleted_at is not None:
        raise VavError("MEDIA_NOT_FOUND", "Media was not found.", status_code=404)
    await media_service.complete(session, asset, payload.checksum_sha256)
    return success({"status": "ready"}, request_id_from_request(request))


@router.get("/admin/media")
async def list_media(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("content.media.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    assets = (
        await session.scalars(
            select(MediaAsset)
            .where(MediaAsset.deleted_at.is_(None))
            .order_by(MediaAsset.created_at.desc())
        )
    ).all()
    return success(
        {
            "items": [
                {
                    "id": str(asset.id),
                    "filename": asset.original_filename,
                    "mime_type": asset.mime_type,
                    "byte_size": asset.byte_size,
                    "visibility": asset.visibility,
                    "processing_status": asset.processing_status,
                }
                for asset in assets
            ]
        },
        request_id_from_request(request),
    )


@router.get("/admin/media/{asset_id}")
async def get_media(
    asset_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("content.media.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    asset = await session.get(MediaAsset, asset_id)
    if asset is None or asset.deleted_at is not None:
        raise VavError("MEDIA_NOT_FOUND", "Media was not found.", status_code=404)
    localizations = list(
        (
            await session.scalars(
                select(MediaAssetLocalization)
                .where(MediaAssetLocalization.media_id == asset.id)
                .order_by(MediaAssetLocalization.locale)
            )
        ).all()
    )
    return success(
        {
            "id": str(asset.id),
            "filename": asset.original_filename,
            "media_type": asset.media_type,
            "mime_type": asset.mime_type,
            "byte_size": asset.byte_size,
            "visibility": asset.visibility,
            "processing_status": asset.processing_status,
            "width": asset.width,
            "height": asset.height,
            "localizations": {
                item.locale: {
                    "alt_text": item.alt_text,
                    "caption": item.caption,
                    "accessibility_description": item.accessibility_description,
                }
                for item in localizations
            },
        },
        request_id_from_request(request),
    )


@router.get("/public/media/{asset_id}")
async def public_media(
    asset_id: UUID,
    request: Request,
    variant: str | None = None,
    session: AsyncSession = Depends(get_database_session),
) -> Response:
    asset = await session.get(MediaAsset, asset_id)
    if (
        asset is None
        or asset.deleted_at is not None
        or asset.visibility != "public"
        or asset.processing_status != "ready"
    ):
        raise VavError("MEDIA_NOT_FOUND", "Media was not found.", status_code=404)
    payload, media_type = await media_service.read_public(asset, variant)
    return Response(
        content=payload,
        media_type=media_type,
        headers={
            "Cache-Control": "public, max-age=300",
            "X-Request-ID": request_id_from_request(request),
        },
    )


@router.patch("/admin/media/{asset_id}")
async def update_media(
    asset_id: UUID,
    payload: MediaUpdateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("content.media.update")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    asset = await session.get(MediaAsset, asset_id, with_for_update=True)
    if asset is None or asset.deleted_at is not None:
        raise VavError("MEDIA_NOT_FOUND", "Media was not found.", status_code=404)
    if payload.visibility is not None:
        if payload.visibility not in {"public", "private"}:
            raise VavError("MEDIA_VISIBILITY_INVALID", "Media visibility is invalid.")
        asset.visibility = payload.visibility
    localized = await session.get(MediaAssetLocalization, (asset.id, payload.locale))
    if localized is None:
        localized = MediaAssetLocalization(
            media_id=asset.id,
            locale=payload.locale,
            alt_text=payload.alt_text,
            caption=payload.caption,
            accessibility_description=payload.accessibility_description,
        )
        session.add(localized)
    else:
        localized.alt_text = payload.alt_text
        localized.caption = payload.caption
        localized.accessibility_description = payload.accessibility_description
    record_security_event(
        session,
        event_type="content.media.updated",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="media_asset",
        target_id=asset.id,
        metadata={"locale": payload.locale, "visibility": asset.visibility},
    )
    await session.commit()
    return success({"status": "updated"}, request_id_from_request(request))


@router.get("/admin/media/{asset_id}/references")
async def media_references(
    asset_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("content.media.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    references = await media_service.references(session, asset_id)
    return success(
        {"items": [{"entry_id": str(item.entry_id), "locale": item.locale} for item in references]},
        request_id_from_request(request),
    )


@router.delete("/admin/media/{asset_id}")
async def delete_media(
    asset_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("content.media.delete")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    asset = await session.get(MediaAsset, asset_id, with_for_update=True)
    if asset is None:
        raise VavError("MEDIA_NOT_FOUND", "Media was not found.", status_code=404)
    if await media_service.references(session, asset_id):
        raise VavError("MEDIA_IN_USE", "Referenced media cannot be deleted.", status_code=409)
    asset.deleted_at = datetime.now(UTC)
    record_security_event(
        session,
        event_type="content.media.deleted",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="media_asset",
        target_id=asset.id,
    )
    await session.commit()
    return success({"status": "deleted"}, request_id_from_request(request))


@router.get("/admin/navigation")
async def admin_navigation(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("content.navigation.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    menus = list(
        (await session.scalars(select(NavigationMenu).order_by(NavigationMenu.code))).all()
    )
    result: list[dict[str, object]] = []
    for menu in menus:
        items = list(
            (
                await session.scalars(
                    select(NavigationItem)
                    .where(NavigationItem.menu_id == menu.id)
                    .order_by(NavigationItem.sort_order, NavigationItem.id)
                )
            ).all()
        )
        localized_rows = (
            await session.execute(
                select(
                    NavigationItemLocalization.navigation_item_id,
                    NavigationItemLocalization.locale,
                    NavigationItemLocalization.label,
                ).where(
                    NavigationItemLocalization.navigation_item_id.in_(
                        [item.id for item in items]
                    )
                )
            )
        ).all()
        localized_by_item: dict[UUID, dict[str, str]] = {}
        for item_id, locale, label in localized_rows:
            localized_by_item.setdefault(item_id, {})[locale] = label
        result.append(
            {
                "id": str(menu.id),
                "code": menu.code,
                "name": menu.name,
                "is_active": menu.is_active,
                "items": [
                    {
                        "id": str(item.id),
                        "internal_name": item.internal_name,
                        "link_type": item.link_type,
                        "route_name": item.route_name,
                        "external_url": item.external_url,
                        "sort_order": item.sort_order,
                        "open_in_new_tab": item.open_in_new_tab,
                        "required_auth": item.required_auth,
                        "is_active": item.is_active,
                        "localizations": localized_by_item.get(item.id, {}),
                    }
                    for item in items
                ],
            }
        )
    return success({"items": result}, request_id_from_request(request))


@router.put("/admin/navigation/{menu_code}")
async def update_navigation(
    menu_code: str,
    payload: NavigationMenuUpdateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(
        require_permission("content.navigation.manage")
    ),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    menu = await session.scalar(
        select(NavigationMenu).where(NavigationMenu.code == menu_code).with_for_update()
    )
    if menu is None:
        raise VavError("NAVIGATION_NOT_FOUND", "Navigation was not found.", status_code=404)
    target_entry_ids = {
        item.target_entry_id for item in payload.items if item.target_entry_id is not None
    }
    if target_entry_ids:
        existing_entry_ids = set(
            (
                await session.scalars(
                    select(ContentEntry.id).where(ContentEntry.id.in_(target_entry_ids))
                )
            ).all()
        )
        if existing_entry_ids != target_entry_ids:
            raise VavError(
                "NAVIGATION_TARGET_NOT_FOUND",
                "A navigation content target was not found.",
                status_code=422,
            )
    existing_item_ids = list(
        (
            await session.scalars(
                select(NavigationItem.id).where(NavigationItem.menu_id == menu.id)
            )
        ).all()
    )
    if existing_item_ids:
        await session.execute(
            update(NavigationItem)
            .where(NavigationItem.id.in_(existing_item_ids))
            .values(parent_id=None)
        )
        await session.execute(
            delete(NavigationItemLocalization).where(
                NavigationItemLocalization.navigation_item_id.in_(existing_item_ids)
            )
        )
        await session.execute(
            delete(NavigationItem).where(NavigationItem.id.in_(existing_item_ids))
        )
    menu.name = payload.name
    menu.is_active = payload.is_active
    for item_input in payload.items:
        values = item_input.model_dump(exclude={"localizations"})
        item = NavigationItem(menu_id=menu.id, **values)
        session.add(item)
        await session.flush()
        for localized in item_input.localizations:
            session.add(
                NavigationItemLocalization(
                    navigation_item_id=item.id,
                    **localized.model_dump(),
                )
            )
    record_security_event(
        session,
        event_type="content.navigation.updated",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="navigation_menu",
        target_id=menu.id,
        reason=payload.reason,
        after_state={"code": menu.code, "item_count": len(payload.items)},
    )
    await session.commit()
    await get_redis().delete(f"cms:navigation:{menu_code}")
    return success(
        {"status": "updated", "item_count": len(payload.items)},
        request_id_from_request(request),
    )


@router.get("/public/navigation/{menu_code}")
async def public_navigation(
    menu_code: str,
    request: Request,
    locale: str = "zh-CN",
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    menu = await session.scalar(
        select(NavigationMenu).where(
            NavigationMenu.code == menu_code, NavigationMenu.is_active.is_(True)
        )
    )
    if menu is None:
        raise VavError("NAVIGATION_NOT_FOUND", "Navigation was not found.", status_code=404)
    rows = (
        await session.execute(
            select(NavigationItem, NavigationItemLocalization.label)
            .join(
                NavigationItemLocalization,
                NavigationItemLocalization.navigation_item_id == NavigationItem.id,
            )
            .where(
                NavigationItem.menu_id == menu.id,
                NavigationItem.is_active.is_(True),
                NavigationItemLocalization.locale == locale,
            )
            .order_by(NavigationItem.sort_order)
        )
    ).all()
    target_entry_ids = {
        item.target_entry_id for item, _ in rows if item.target_entry_id is not None
    }
    target_slugs = (
        {
            entry_id: slug
            for entry_id, slug in (
                await session.execute(
                    select(ContentEntry.id, ContentEntry.canonical_slug).where(
                        ContentEntry.id.in_(target_entry_ids)
                    )
                )
            ).all()
        }
        if target_entry_ids
        else {}
    )
    return success(
        {
            "code": menu.code,
            "items": [
                {
                    "id": str(item.id),
                    "label": label,
                    "link_type": item.link_type,
                    "external_url": item.external_url,
                    "route_name": item.route_name,
                    "target_slug": target_slugs.get(item.target_entry_id),
                    "open_in_new_tab": item.open_in_new_tab,
                    "required_auth": item.required_auth,
                }
                for item, label in rows
            ],
        },
        request_id_from_request(request),
    )


@router.get("/public/site-settings")
async def public_site_settings(
    request: Request,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    settings = (
        await session.scalars(
            select(SiteSetting)
            .where(SiteSetting.is_public.is_(True))
            .order_by(SiteSetting.setting_key)
        )
    ).all()
    return success(
        {"items": {setting.setting_key: setting.value for setting in settings}},
        request_id_from_request(request),
    )


@router.get("/admin/site-settings")
async def admin_site_settings(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("content.settings.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    settings = list(
        (await session.scalars(select(SiteSetting).order_by(SiteSetting.setting_key))).all()
    )
    return success(
        {
            "items": [
                {
                    "setting_key": setting.setting_key,
                    "value": setting.value,
                    "value_type": setting.value_type,
                    "is_public": setting.is_public,
                    "updated_at": setting.updated_at.isoformat(),
                }
                for setting in settings
            ]
        },
        request_id_from_request(request),
    )


@router.put("/admin/site-settings/{setting_key}")
async def update_site_setting(
    setting_key: str,
    payload: SiteSettingRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("content.settings.manage")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    forbidden = ("secret", "password", "private_key", "token", "database_url", "api_key")
    if payload.is_public and any(marker in setting_key.casefold() for marker in forbidden):
        raise VavError(
            "PRIVATE_SETTING_EXPOSURE_BLOCKED",
            "Secret-like settings cannot be public.",
            status_code=409,
        )
    setting = await session.get(SiteSetting, setting_key, with_for_update=True)
    if setting is None:
        setting = SiteSetting(
            setting_key=setting_key,
            value=payload.value,
            value_type=payload.value_type,
            is_public=payload.is_public,
            updated_by=principal.user.id,
        )
        session.add(setting)
    else:
        setting.value = payload.value
        setting.value_type = payload.value_type
        setting.is_public = payload.is_public
        setting.updated_by = principal.user.id
    record_security_event(
        session,
        event_type="content.site_setting.updated",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="site_setting",
        reason=setting_key,
    )
    await session.commit()
    return success({"status": "updated"}, request_id_from_request(request))


@router.post("/public/contact-submissions", status_code=status.HTTP_202_ACCEPTED)
async def submit_contact(
    payload: ContactSubmissionRequest,
    request: Request,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    ip_hash, user_agent_hash = request_fingerprint(request)
    await enforce_rate_limit(f"rate:contact:ip:{ip_hash}", limit=5, window_seconds=3600)
    await enforce_rate_limit(
        f"rate:contact:email:{privacy_hash(str(payload.email))}",
        limit=3,
        window_seconds=3600,
    )
    if payload.website:
        return success({"status": "accepted"}, request_id_from_request(request))
    if payload.form_started_at and datetime.now(UTC) - payload.form_started_at < timedelta(
        seconds=3
    ):
        raise VavError("CONTACT_FORM_TOO_FAST", "Contact form was submitted too quickly.")
    submission = ContactSubmission(
        submission_type=payload.submission_type,
        name=payload.name,
        email=str(payload.email),
        region=payload.region,
        subject=payload.subject,
        message=payload.message,
        locale=payload.locale,
        privacy_consent_version=payload.privacy_consent_version,
        privacy_consented_at=datetime.now(UTC),
        source_page=payload.source_page,
        ip_address_hash=ip_hash,
        user_agent_hash=user_agent_hash,
    )
    session.add(submission)
    await session.flush()
    record_security_event(
        session,
        event_type="contact.submission.created",
        actor_type="anonymous",
        target_type="contact_submission",
        target_id=submission.id,
    )
    await session.commit()
    return success({"status": "accepted"}, request_id_from_request(request))


@router.get("/admin/contact-submissions")
async def admin_contact_submissions(
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("contact.submissions.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    submissions = (
        await session.scalars(
            select(ContactSubmission).order_by(ContactSubmission.created_at.desc())
        )
    ).all()
    return success(
        {
            "items": [
                {
                    "id": str(item.id),
                    "submission_type": item.submission_type,
                    "name": item.name,
                    "email": item.email,
                    "region": item.region,
                    "subject": item.subject,
                    "message": item.message,
                    "status": item.status,
                    "locale": item.locale,
                    "privacy_consent_version": item.privacy_consent_version,
                    "created_at": item.created_at.isoformat(),
                }
                for item in submissions
            ]
        },
        request_id_from_request(request),
    )


@router.get("/admin/contact-submissions/{submission_id}")
async def get_contact_submission(
    submission_id: UUID,
    request: Request,
    _: AuthenticatedPrincipal = Depends(require_permission("contact.submissions.read")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    item = await session.get(ContactSubmission, submission_id)
    if item is None:
        raise VavError("CONTACT_NOT_FOUND", "Contact submission was not found.", status_code=404)
    return success(
        {
            "id": str(item.id),
            "submission_type": item.submission_type,
            "name": item.name,
            "email": item.email,
            "region": item.region,
            "subject": item.subject,
            "message": item.message,
            "status": item.status,
            "assigned_to": str(item.assigned_to) if item.assigned_to else None,
            "locale": item.locale,
            "privacy_consent_version": item.privacy_consent_version,
            "privacy_consented_at": item.privacy_consented_at.isoformat(),
            "source_page": item.source_page,
            "created_at": item.created_at.isoformat(),
            "resolved_at": item.resolved_at.isoformat() if item.resolved_at else None,
        },
        request_id_from_request(request),
    )


@router.patch("/admin/contact-submissions/{submission_id}/status")
async def update_contact_status(
    submission_id: UUID,
    payload: ContactStatusRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("contact.submissions.resolve")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    submission = await session.get(ContactSubmission, submission_id, with_for_update=True)
    if submission is None:
        raise VavError("CONTACT_NOT_FOUND", "Contact submission was not found.", status_code=404)
    if payload.status not in {
        "new",
        "in_progress",
        "waiting_external",
        "resolved",
        "spam",
        "archived",
    }:
        raise VavError("CONTACT_STATUS_INVALID", "Contact status is invalid.")
    before = submission.status
    submission.status = payload.status
    submission.resolved_at = datetime.now(UTC) if payload.status == "resolved" else None
    record_security_event(
        session,
        event_type="contact.submission.status_changed",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="contact_submission",
        target_id=submission.id,
        reason=payload.reason,
        before_state={"status": before},
        after_state={"status": submission.status},
    )
    await session.commit()
    return success({"status": submission.status}, request_id_from_request(request))


@router.post("/admin/contact-submissions/{submission_id}/assign")
async def assign_contact_submission(
    submission_id: UUID,
    payload: ContactAssignRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("contact.submissions.assign")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    submission = await session.get(ContactSubmission, submission_id, with_for_update=True)
    if submission is None:
        raise VavError("CONTACT_NOT_FOUND", "Contact submission was not found.", status_code=404)
    submission.assigned_to = payload.assigned_to
    if submission.status == "new":
        submission.status = "in_progress"
    record_security_event(
        session,
        event_type="contact.submission.assigned",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="contact_submission",
        target_id=submission.id,
        reason=payload.reason,
        after_state={"assigned_to": str(payload.assigned_to)},
    )
    await session.commit()
    return success(
        {"assigned_to": str(submission.assigned_to), "status": submission.status},
        request_id_from_request(request),
    )


@router.post("/admin/contact-submissions/{submission_id}/resolve")
async def resolve_contact_submission(
    submission_id: UUID,
    payload: ContactResolveRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_permission("contact.submissions.resolve")),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    submission = await session.get(ContactSubmission, submission_id, with_for_update=True)
    if submission is None:
        raise VavError("CONTACT_NOT_FOUND", "Contact submission was not found.", status_code=404)
    submission.status = "resolved"
    submission.resolved_at = datetime.now(UTC)
    record_security_event(
        session,
        event_type="contact.submission.resolved",
        actor_type="admin",
        actor_user_id=principal.user.id,
        target_type="contact_submission",
        target_id=submission.id,
        reason=payload.resolution,
    )
    await session.commit()
    return success({"status": submission.status}, request_id_from_request(request))


@router.post("/admin/contact-submissions/export")
async def export_contact_submissions(
    _: AuthenticatedPrincipal = Depends(require_permission("contact.submissions.export")),
    session: AsyncSession = Depends(get_database_session),
) -> StreamingResponse:
    submissions = list(
        (
            await session.scalars(select(ContactSubmission).order_by(ContactSubmission.created_at))
        ).all()
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "submission_type",
            "name",
            "email",
            "region",
            "subject",
            "status",
            "locale",
            "privacy_consent_version",
            "created_at",
        ]
    )
    for item in submissions:
        writer.writerow(
            [
                item.id,
                item.submission_type,
                item.name,
                item.email,
                item.region,
                item.subject,
                item.status,
                item.locale,
                item.privacy_consent_version,
                item.created_at.isoformat(),
            ]
        )
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=contact-submissions.csv"},
    )
