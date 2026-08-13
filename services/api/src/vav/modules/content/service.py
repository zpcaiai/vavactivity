from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.models.content import (
    ContentEntry,
    ContentLocalization,
    ContentPreviewToken,
    ContentVersion,
    MediaAsset,
    MediaAssetLocalization,
    TestimonialMetadata,
)
from vav.modules.content.domain import ContentEntryType, ContentStatus, TranslationStatus
from vav.modules.content.schemas import LocalizationInput
from vav.modules.identity.audit import record_security_event
from vav.modules.identity.security import opaque_token, sha256_token


def localization_dict(localization: ContentLocalization) -> dict[str, object]:
    return {
        "locale": localization.locale,
        "localized_slug": localization.localized_slug,
        "title": localization.title,
        "subtitle": localization.subtitle,
        "excerpt": localization.excerpt,
        "content_blocks": localization.content_blocks,
        "plain_text": localization.plain_text,
        "seo_title": localization.seo_title,
        "seo_description": localization.seo_description,
        "social_title": localization.social_title,
        "social_description": localization.social_description,
        "cover_media_id": (
            str(localization.cover_media_id) if localization.cover_media_id else None
        ),
        "translation_status": localization.translation_status,
    }


def content_dict(
    entry: ContentEntry, localizations: list[ContentLocalization]
) -> dict[str, object]:
    return {
        "id": str(entry.id),
        "entry_type": entry.entry_type,
        "internal_name": entry.internal_name,
        "canonical_slug": entry.canonical_slug,
        "status": entry.status,
        "default_locale": entry.default_locale,
        "visibility": entry.visibility,
        "version": entry.version,
        "current_version": entry.current_version,
        "published_at": entry.published_at.isoformat() if entry.published_at else None,
        "localizations": {
            localization.locale: localization_dict(localization) for localization in localizations
        },
    }


class ContentService:
    async def _localizations(
        self, session: AsyncSession, entry_id: UUID
    ) -> list[ContentLocalization]:
        return list(
            (
                await session.scalars(
                    select(ContentLocalization)
                    .where(ContentLocalization.entry_id == entry_id)
                    .order_by(ContentLocalization.locale)
                )
            ).all()
        )

    async def next_revision_number(self, session: AsyncSession, entry_id: UUID) -> int:
        """Return the next free number in this entry's revision history.

        The number has to come from ``content_versions`` itself, not from a
        counter on the entry. ``cms_publishing`` appends to the same history,
        so a counter this console maintains alone drifts behind the real head
        the moment an editor uses the other console — and the next save here
        then collides with a number that already exists.
        """

        # ``no_autoflush`` matters: callers ask for this number in the middle of
        # mutating the entry, and an autoflush here would push a half-applied
        # row to the database — for example a status already set to
        # ``published`` before the live-revision pin has been assigned, which
        # the ``published_revision_present`` check constraint then rejects.
        with session.no_autoflush:
            head = await session.scalar(
                select(func.max(ContentVersion.version_number)).where(
                    ContentVersion.entry_id == entry_id
                )
            )
        return int(head or 0) + 1

    async def snapshot(
        self,
        session: AsyncSession,
        entry: ContentEntry,
        *,
        actor_id: UUID,
        change_summary: str,
    ) -> ContentVersion:
        localizations = await self._localizations(session, entry.id)
        number = await self.next_revision_number(session, entry.id)
        version = ContentVersion(
            entry_id=entry.id,
            version_number=number,
            snapshot=content_dict(entry, localizations),
            change_summary=change_summary,
            created_by=actor_id,
        )
        session.add(version)
        # ``current_version`` now means one thing only: the head of history.
        # Writing it here keeps it true no matter which console appended.
        entry.current_version = number
        return version

    async def create(
        self,
        session: AsyncSession,
        *,
        entry_type: ContentEntryType,
        internal_name: str,
        canonical_slug: str,
        default_locale: str,
        localization: LocalizationInput,
        change_summary: str,
        actor_id: UUID,
    ) -> ContentEntry:
        if localization.locale != default_locale:
            raise VavError(
                "DEFAULT_LOCALIZATION_REQUIRED",
                "Initial localization must match the default locale.",
            )
        existing = await session.scalar(
            select(ContentEntry).where(
                ContentEntry.entry_type == entry_type,
                ContentEntry.canonical_slug == canonical_slug,
            )
        )
        if existing:
            raise VavError("CONTENT_SLUG_CONFLICT", "Content slug already exists.", status_code=409)
        entry = ContentEntry(
            id=uuid4(),
            entry_type=entry_type,
            internal_name=internal_name,
            canonical_slug=canonical_slug,
            default_locale=default_locale,
            author_id=actor_id,
        )
        session.add(entry)
        await session.flush()
        session.add(self._new_localization(entry.id, localization))
        await session.flush()
        await self.snapshot(session, entry, actor_id=actor_id, change_summary=change_summary)
        record_security_event(
            session,
            event_type="content.entry.created",
            actor_type="admin",
            actor_user_id=actor_id,
            target_type="content_entry",
            target_id=entry.id,
        )
        await session.commit()
        return entry

    def _new_localization(self, entry_id: UUID, payload: LocalizationInput) -> ContentLocalization:
        values = payload.model_dump(mode="json")
        values["content_blocks"] = [
            block.model_dump(mode="json") for block in payload.content_blocks
        ]
        values.pop("expected_version", None)
        values.pop("change_summary", None)
        return ContentLocalization(entry_id=entry_id, **values)

    async def update_localization(
        self,
        session: AsyncSession,
        *,
        entry: ContentEntry,
        payload: LocalizationInput,
        expected_version: int,
        change_summary: str,
        actor_id: UUID,
    ) -> ContentLocalization:
        if entry.version != expected_version:
            raise VavError(
                "CONTENT_VERSION_CONFLICT",
                "The content has been updated by another editor.",
                status_code=409,
            )
        if entry.status == ContentStatus.PUBLISHED:
            entry.status = ContentStatus.DRAFT
            entry.reviewer_id = None
            for other in await self._localizations(session, entry.id):
                if other.locale != payload.locale:
                    other.translation_status = TranslationStatus.OUTDATED
        localization = await session.scalar(
            select(ContentLocalization)
            .where(
                ContentLocalization.entry_id == entry.id,
                ContentLocalization.locale == payload.locale,
            )
            .with_for_update()
        )
        values = payload.model_dump(mode="json")
        values["content_blocks"] = [
            block.model_dump(mode="json") for block in payload.content_blocks
        ]
        if localization is None:
            localization = ContentLocalization(entry_id=entry.id, **values)
            session.add(localization)
        else:
            for field, value in values.items():
                setattr(localization, field, value)
        entry.version += 1
        await session.flush()
        await self.snapshot(session, entry, actor_id=actor_id, change_summary=change_summary)
        record_security_event(
            session,
            event_type="content.translation.updated",
            actor_type="admin",
            actor_user_id=actor_id,
            target_type="content_entry",
            target_id=entry.id,
            metadata={"locale": payload.locale},
        )
        await session.commit()
        return localization

    async def transition(
        self,
        session: AsyncSession,
        *,
        entry: ContentEntry,
        action: str,
        actor_id: UUID,
        reason: str,
        scheduled_at: datetime | None = None,
    ) -> None:
        now = datetime.now(UTC)
        before = entry.status
        if action == "submit-review" and entry.status == ContentStatus.DRAFT:
            entry.status = ContentStatus.IN_REVIEW
        elif action in {"approve", "publish"} and entry.status in {
            ContentStatus.DRAFT,
            ContentStatus.IN_REVIEW,
            ContentStatus.SCHEDULED,
        }:
            if (
                get_settings().cms_require_review_for_publish
                and entry.status == ContentStatus.DRAFT
            ):
                raise VavError(
                    "CONTENT_REVIEW_REQUIRED",
                    "Content must be submitted for review before publication.",
                    status_code=409,
                )
            ready = await session.scalar(
                select(ContentLocalization.id).where(
                    ContentLocalization.entry_id == entry.id,
                    ContentLocalization.translation_status == TranslationStatus.READY,
                )
            )
            if ready is None:
                raise VavError(
                    "CONTENT_TRANSLATION_NOT_READY",
                    "At least one localization must be ready.",
                    status_code=409,
                )
            await self._validate_publication_media(session, entry.id)
            if entry.entry_type == ContentEntryType.TESTIMONIAL:
                metadata = await session.get(TestimonialMetadata, entry.id)
                if (
                    metadata is None
                    or metadata.consent_status != "approved"
                    or metadata.consent_record_id is None
                ):
                    raise VavError(
                        "TESTIMONIAL_CONSENT_REQUIRED",
                        "Publishing requires an approved consent record.",
                        status_code=409,
                    )
            entry.status = ContentStatus.PUBLISHED
            entry.published_at = now
            entry.published_by = actor_id
            # Pin which revision went live. ``snapshot`` below appends one more
            # row for this transition itself, so the live revision is that new
            # number — the same thing a member will read.
            entry.published_revision_number = await self.next_revision_number(session, entry.id)
        elif action == "reject" and entry.status == ContentStatus.IN_REVIEW:
            entry.status = ContentStatus.DRAFT
        elif action == "schedule" and scheduled_at and scheduled_at > now:
            entry.status = ContentStatus.SCHEDULED
            entry.scheduled_publish_at = scheduled_at
        elif action == "archive" and entry.status != ContentStatus.ARCHIVED:
            entry.status = ContentStatus.ARCHIVED
            entry.archived_at = now
        elif action == "restore" and entry.status == ContentStatus.ARCHIVED:
            entry.status = ContentStatus.DRAFT
            entry.archived_at = None
        else:
            raise VavError(
                "CONTENT_STATE_TRANSITION_INVALID",
                "Content state transition is invalid.",
                status_code=409,
            )
        entry.version += 1
        await session.flush()
        await self.snapshot(
            session,
            entry,
            actor_id=actor_id,
            change_summary=f"{action}: {reason}",
        )
        record_security_event(
            session,
            event_type=f"content.entry.{action.replace('-', '_')}",
            actor_type="admin",
            actor_user_id=actor_id,
            target_type="content_entry",
            target_id=entry.id,
            reason=reason,
            before_state={"status": before},
            after_state={"status": entry.status},
        )
        await session.commit()

    async def _validate_publication_media(
        self,
        session: AsyncSession,
        entry_id: UUID,
    ) -> None:
        errors: list[str] = []
        for localization in await self._localizations(session, entry_id):
            if localization.translation_status != TranslationStatus.READY:
                continue
            references: list[tuple[UUID, bool]] = []
            if localization.cover_media_id:
                references.append((localization.cover_media_id, False))
            for block in localization.content_blocks:
                if block.get("type") not in {"image", "hero"}:
                    continue
                data = block.get("data")
                if not isinstance(data, dict):
                    continue
                raw_media_id = (
                    data.get("media_id")
                    if block.get("type") == "image"
                    else data.get("background_media_id")
                )
                if not raw_media_id:
                    continue
                try:
                    media_id = UUID(str(raw_media_id))
                except ValueError:
                    errors.append(f"{localization.locale}: invalid media reference")
                    continue
                references.append(
                    (
                        media_id,
                        bool(data.get("decorative", block.get("type") == "hero")),
                    )
                )
            for media_id, decorative in references:
                asset = await session.get(MediaAsset, media_id)
                if (
                    asset is None
                    or asset.deleted_at is not None
                    or asset.processing_status != "ready"
                    or asset.visibility != "public"
                ):
                    errors.append(
                        f"{localization.locale}: media {media_id} is not public and ready"
                    )
                    continue
                if not decorative:
                    metadata = await session.get(
                        MediaAssetLocalization,
                        (media_id, localization.locale),
                    )
                    if metadata is None or not (metadata.alt_text or "").strip():
                        errors.append(f"{localization.locale}: media {media_id} requires alt text")
        if errors:
            raise VavError(
                "CONTENT_MEDIA_VALIDATION_FAILED",
                "Content media is not ready for publication.",
                status_code=409,
                details=[{"errors": errors}],
            )

    async def create_preview_token(
        self,
        session: AsyncSession,
        *,
        entry_id: UUID,
        locale: str | None,
        actor_id: UUID,
    ) -> str:
        if await session.get(ContentEntry, entry_id) is None:
            raise VavError("CONTENT_NOT_FOUND", "Content was not found.", status_code=404)
        raw_token = opaque_token()
        session.add(
            ContentPreviewToken(
                entry_id=entry_id,
                token_hash=sha256_token(raw_token),
                locale=locale,
                created_by=actor_id,
                expires_at=datetime.now(UTC)
                + timedelta(minutes=get_settings().cms_preview_token_ttl_minutes),
            )
        )
        await session.commit()
        return raw_token


content_service = ContentService()
