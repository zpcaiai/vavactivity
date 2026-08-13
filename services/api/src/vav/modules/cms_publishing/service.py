"""Transactional bilingual CMS service (B19 part 2 / CMS-001).

Design notes:

* **One set of content tables.** Authoring writes ``content_entries``,
  ``content_localizations``, ``content_versions`` and
  ``content_preview_tokens`` - the tables the public site already reads. The
  earlier ``cms_*`` namespace was a second, parallel copy of the same idea, so
  an editor who published through this console produced nothing on the site.
* **Sanitizing happens on write.** Every body that enters
  ``content_localizations`` has already been through
  ``domain.sanitize_rich_text``, and what was removed is recorded on the
  version snapshot. Sanitizing on read would leave the raw payload for an
  export, a search indexer or an email renderer to reproduce faithfully.
* **Every write appends a version.** ``content_versions`` is append-only here
  and its ``snapshot`` carries the full locale payload plus the SEO fields, so
  a rollback is a new version pointing at an old body rather than an UPDATE
  that erases what happened.
* **Reads state their locale honestly.** :func:`read_public_entry` returns the
  resolved content together with ``translation_fallback`` and the locale that
  was actually served.
* All rules live in :mod:`vav.modules.cms_publishing.domain`; this layer only
  loads state and persists it.

Two things the shared schema cannot express, handled here rather than by
inventing columns:

* ``content_preview_tokens`` has no revision column, so the pinned revision
  travels in the token itself and is authenticated by the stored token hash
  (see :func:`grant_preview`).
* ``content_localizations`` gained ``canonical_path`` and ``robots`` in
  migration ``20260812_0109``; both are stored on the live row.
  Both are still validated on write and kept in the version snapshot; the
  canonical path served to readers is derived from the entry's slug.
"""

# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime
from html import escape
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.cms_publishing.domain import (
    CmsRuleError,
    EntryStatus,
    LocaleStatus,
    LocalizedBody,
    Revision,
    RevisionAction,
    SeoMetadata,
    build_preview_claim,
    content_fingerprint,
    derive_seo_defaults,
    ensure_publishable,
    extract_plain_text,
    is_entry_member_visible,
    next_revision_number,
    plan_rollback,
    resolve_localization,
    sanitize_rich_text,
    validate_entry_transition,
    validate_seo_metadata,
)

#: ``content_entries.entry_type`` is VARCHAR(32); the request schema allows 64.
#: Checked here so an over-long type is a clean 422 rather than a DataError.
ENTRY_TYPE_MAX_LENGTH = 32

#: ``content_entries.internal_name`` is NOT NULL VARCHAR(160). The console does
#: not ask for one, so the default-locale title stands in for it.
INTERNAL_NAME_MAX_LENGTH = 160


def _now() -> datetime:
    return datetime.now(UTC)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _fail(error: CmsRuleError, status_code: int = 422) -> VavError:
    """Translate a pure-domain violation into the platform error envelope.

    ``VavError.details`` is a list in this codebase, so the rule's structured
    context is wrapped rather than passed through as a mapping.
    """

    return VavError(
        error.code,
        error.message,
        status_code=status_code,
        details=[error.details] if error.details else None,
    )


def enabled() -> None:
    if not get_settings().cms_publishing_enabled:
        raise VavError(
            "CMS_PUBLISHING_DISABLED", "Content publishing is not enabled.", status_code=503
        )


async def _publish_event(
    session: AsyncSession, topic: str, aggregate_id: UUID, payload: dict[str, Any]
) -> None:
    await session.execute(
        text(
            "INSERT INTO outbox_events (topic,aggregate_type,aggregate_id,payload) "
            "VALUES (:topic,'content_entry',:id,CAST(:payload AS jsonb))"
        ),
        {"topic": topic, "id": str(aggregate_id), "payload": _json(payload)},
    )


async def _audit(
    session: AsyncSession,
    *,
    entry_id: UUID,
    revision_number: int | None,
    action: str,
    actor_id: UUID | None,
    reason: str | None = None,
) -> None:
    """Record who moved this page, when and why.

    There is no CMS-private publish-event table any more. ``audit_events`` is
    the platform log the rest of the modules write to and a trigger rejects
    UPDATE and DELETE on it, so the publishing trail is append-only and lands
    where operators already look.
    """

    await session.execute(
        text(
            "INSERT INTO audit_events (actor_id,actor_type,action,subject_type,subject_id,reason,context,occurred_at) "
            "VALUES (:actor,'administrator',:action,'content_entry',:entry_id,:reason,CAST(:context AS jsonb),now())"
        ),
        {
            "actor": str(actor_id) if actor_id else None,
            "action": f"cms.entry.{action}",
            "entry_id": str(entry_id),
            "reason": reason,
            "context": _json({"revision_number": revision_number}),
        },
    )


# ---------------------------------------------------------------------------
# Sanitizing and body assembly
# ---------------------------------------------------------------------------

#: The block that carries an entry's body inside ``content_blocks``.
BODY_BLOCK_ID = "body"

#: Marks a block this module wrote, i.e. one whose HTML already went through
#: the allow-list sanitizer. Anything else is sanitized again on read.
SANITIZED_BLOCK_FORMAT = "sanitized_html"


def _content_blocks(body_html: str) -> list[dict[str, Any]]:
    """Wrap sanitized HTML as the structured block the site renders.

    ``content_localizations`` stores bodies in ``content_blocks``; there is no
    HTML column. The block matches the platform's ``rich_text`` block shape so
    the existing public renderer can read it unchanged.
    """

    return [
        {
            "id": BODY_BLOCK_ID,
            "type": "rich_text",
            "version": 1,
            "data": {"document": {"format": SANITIZED_BLOCK_FORMAT, "html": body_html}},
        }
    ]


def _html_from_blocks(blocks: Any, *, plain_text: str | None = None) -> str:
    """Recover an entry body from ``content_blocks``.

    Rows written by this module carry the sanitizer marker and are served as
    stored. Rows written by anything else are put through the sanitizer before
    they are served, because the "sanitized on write" guarantee only covers
    what this module wrote.
    """

    parts: list[str] = []
    for block in blocks or []:
        if not isinstance(block, dict) or block.get("type") != "rich_text":
            continue
        data = block.get("data")
        document = data.get("document") if isinstance(data, dict) else None
        if not isinstance(document, dict):
            continue
        html = document.get("html")
        if not isinstance(html, str) or not html:
            continue
        if document.get("format") == SANITIZED_BLOCK_FORMAT:
            parts.append(html)
            continue
        try:
            parts.append(sanitize_rich_text(html).html)
        except CmsRuleError:
            continue
    if parts:
        return "".join(parts)
    return f"<p>{escape(plain_text)}</p>" if plain_text else ""


def _locale_status(value: str | None) -> LocaleStatus:
    """Read a locale's workflow state, tolerating the older vocabulary.

    ``translation_status`` predates this module and carries values the CMS
    workflow does not use (``missing``, ``review_required``, ``outdated``).
    None of them means "live", so an unknown value reads as ``draft`` rather
    than raising on a row this module did not write.
    """

    if not value:
        return LocaleStatus.DRAFT
    try:
        return LocaleStatus(value)
    except ValueError:
        return LocaleStatus.DRAFT


def _sanitize_bodies(
    payload_bodies: list[dict[str, Any]],
) -> tuple[list[LocalizedBody], dict[str, Any]]:
    """Sanitize every locale and report what was stripped, per locale."""

    bodies: list[LocalizedBody] = []
    report: dict[str, Any] = {}
    for raw in payload_bodies:
        try:
            cleaned = sanitize_rich_text(raw["body_html"])
        except CmsRuleError as error:
            raise _fail(error) from error
        bodies.append(
            LocalizedBody(
                locale=raw["locale"],
                title=raw["title"],
                body_html=cleaned.html,
                summary=raw.get("summary", ""),
                status=LocaleStatus(raw.get("status", "draft")),
            )
        )
        report[raw["locale"]] = {
            "removed_tags": list(cleaned.removed_tags),
            "removed_attributes": list(cleaned.removed_attributes),
            "was_modified": cleaned.was_modified,
        }
    return bodies, report


def _seo_from_payload(
    raw: dict[str, Any] | None, body: LocalizedBody, *, entry_code: str
) -> SeoMetadata:
    if raw is None:
        return derive_seo_defaults(body, canonical_path=f"/content/{entry_code}")
    return SeoMetadata(
        seo_title=raw["seo_title"],
        seo_description=raw.get("seo_description", ""),
        canonical_path=raw["canonical_path"],
        robots=tuple(raw.get("robots") or ("index", "follow")),
        og_image_media_id=raw.get("og_image_media_id"),
    )


def _seo_payload(seo: SeoMetadata | None) -> dict[str, Any]:
    """The SEO half of a version snapshot.

    ``canonical_path`` and ``robots`` are stored on
    ``content_localizations``; keeping them here means a rollback still
    restores exactly what the editor approved.
    """

    if seo is None:
        return {}
    return {
        "seo_title": seo.seo_title,
        "seo_description": seo.seo_description,
        "canonical_path": seo.canonical_path,
        "robots": list(seo.robots),
        "og_image_media_id": seo.og_image_media_id,
    }


def _seo_from_snapshot(payload: Any) -> SeoMetadata | None:
    if not isinstance(payload, dict) or not payload:
        return None
    return SeoMetadata(
        seo_title=payload["seo_title"],
        seo_description=payload.get("seo_description", ""),
        canonical_path=payload["canonical_path"],
        robots=tuple(payload.get("robots") or ("index", "follow")),
        og_image_media_id=payload.get("og_image_media_id"),
    )


def _bodies_payload(bodies: list[LocalizedBody]) -> list[dict[str, Any]]:
    return [
        {
            "locale": body.locale,
            "title": body.title,
            "summary": body.summary,
            "body_html": body.body_html,
            "status": body.status.value,
        }
        for body in bodies
    ]


def _bodies_from_snapshot(payload: Any, *, sanitize: bool = False) -> list[LocalizedBody]:
    bodies: list[LocalizedBody] = []
    for item in payload or []:
        if not isinstance(item, dict):
            continue
        body_html = item.get("body_html") or ""
        bodies.append(
            LocalizedBody(
                locale=item["locale"],
                title=item["title"],
                body_html=sanitize_rich_text(body_html).html if sanitize else body_html,
                summary=item.get("summary", ""),
                status=_locale_status(item.get("status")),
            )
        )
    return bodies


def _media_uuid(value: Any) -> str | None:
    """``cover_media_id`` is a UUID column; an opaque media reference is not."""

    if value in (None, ""):
        return None
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


async def _load_entry(
    session: AsyncSession, entry_id: UUID, *, lock: bool = False
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,canonical_slug AS entry_code,entry_type AS content_type,status,"
                    "default_locale,scheduled_publish_at,published_at,"
                    "published_revision_number,current_version AS head_revision_number,"
                    "internal_name,visibility,version "
                    "FROM content_entries WHERE id=:id" + (" FOR UPDATE" if lock else "")
                ),
                {"id": str(entry_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("CMS_ENTRY_NOT_FOUND", "Content entry not found.", status_code=404)
    return dict(row)


async def _load_bodies(session: AsyncSession, entry_id: UUID) -> list[LocalizedBody]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT locale,title,excerpt,content_blocks,plain_text,translation_status "
                    "FROM content_localizations WHERE entry_id=:entry_id ORDER BY locale"
                ),
                {"entry_id": str(entry_id)},
            )
        )
        .mappings()
        .all()
    )
    return [
        LocalizedBody(
            locale=row["locale"],
            title=row["title"],
            body_html=_html_from_blocks(row["content_blocks"], plain_text=row["plain_text"]),
            summary=row["excerpt"] or "",
            status=_locale_status(row["translation_status"]),
        )
        for row in rows
    ]


async def _load_revisions(session: AsyncSession, entry_id: UUID) -> list[Revision]:
    """Read the version history as domain revisions.

    ``content_versions`` is shared with the older content console, whose
    snapshots carry no ``action`` or ``content_hash``. Those rows still count
    as history - a rollback target has to be able to name them - so unknown
    shapes read as an edit rather than raising.
    """

    rows = (
        (
            await session.execute(
                text(
                    "SELECT version_number,snapshot,created_at FROM content_versions "
                    "WHERE entry_id=:entry_id ORDER BY version_number"
                ),
                {"entry_id": str(entry_id)},
            )
        )
        .mappings()
        .all()
    )
    revisions: list[Revision] = []
    for row in rows:
        snapshot = row["snapshot"] if isinstance(row["snapshot"], dict) else {}
        try:
            action = RevisionAction(str(snapshot.get("action") or "edited"))
        except ValueError:
            action = RevisionAction.EDITED
        revisions.append(
            Revision(
                revision_number=int(row["version_number"]),
                content_hash=str(snapshot.get("content_hash") or ""),
                action=action,
                created_at=row["created_at"],
                source_revision_number=snapshot.get("source_revision_number"),
            )
        )
    return revisions


async def _write_revision(
    session: AsyncSession,
    *,
    entry_id: UUID,
    bodies: list[LocalizedBody],
    seo: SeoMetadata | None,
    action: RevisionAction,
    actor_id: UUID,
    change_summary: str,
    source_revision_number: int | None = None,
    sanitizer_report: dict[str, Any] | None = None,
) -> int:
    """Append one ``content_versions`` row.

    Locale payload, SEO payload and the sanitizer report all live in the single
    ``snapshot`` column, which is what makes a rollback restore exactly the
    body, the SEO text and the canonical path an editor approved.
    """

    revisions = await _load_revisions(session, entry_id)
    number = next_revision_number(revisions)
    await session.execute(
        text(
            "INSERT INTO content_versions (entry_id,version_number,snapshot,change_summary,created_by) "
            "VALUES (:entry_id,:number,CAST(:snapshot AS jsonb),:change_summary,:actor)"
        ),
        {
            "entry_id": str(entry_id),
            "number": number,
            "snapshot": _json(
                {
                    "revision_number": number,
                    "action": action.value,
                    "content_hash": content_fingerprint(bodies, seo),
                    "source_revision_number": source_revision_number,
                    "sanitizer_report": sanitizer_report or {},
                    "locales": _bodies_payload(bodies),
                    "seo": _seo_payload(seo),
                }
            ),
            "change_summary": change_summary or action.value,
            "actor": str(actor_id),
        },
    )
    # Keep the head-of-history counter true. The older content console reads it
    # to pick its next snapshot number, so leaving it stale here is what made
    # that console collide on save.
    await session.execute(
        text("UPDATE content_entries SET current_version=:number WHERE id=:entry_id"),
        {"number": number, "entry_id": str(entry_id)},
    )
    return number


async def _replace_locales(
    session: AsyncSession, *, entry_id: UUID, bodies: list[LocalizedBody]
) -> None:
    """Upsert one ``content_localizations`` row per locale.

    ``localized_slug`` is deliberately left alone: it is unique per
    ``(locale, localized_slug)`` across every entry type, so filling it from
    the entry slug would make two entries that legitimately share a slug
    collide. The SEO columns are left alone too - :func:`_write_seo` owns them.
    The row records no editor: ``content_localizations`` has no ``updated_by``
    column, so authorship lives on the version and in the audit log.
    """

    for body in bodies:
        await session.execute(
            text(
                "INSERT INTO content_localizations "
                "(entry_id,locale,title,excerpt,content_blocks,plain_text,translation_status) "
                "VALUES (:entry_id,:locale,:title,:excerpt,CAST(:content_blocks AS jsonb),:plain_text,:translation_status) "
                "ON CONFLICT (entry_id,locale) DO UPDATE SET title=EXCLUDED.title,"
                "excerpt=EXCLUDED.excerpt,content_blocks=EXCLUDED.content_blocks,"
                "plain_text=EXCLUDED.plain_text,translation_status=EXCLUDED.translation_status,"
                "updated_at=now()"
            ),
            {
                "entry_id": str(entry_id),
                "locale": body.locale,
                "title": body.title,
                "excerpt": body.summary,
                "content_blocks": _json(_content_blocks(body.body_html)),
                "plain_text": extract_plain_text(body.body_html),
                "translation_status": body.status.value,
            },
        )


async def _write_seo(
    session: AsyncSession, *, entry_id: UUID, locale: str, seo: SeoMetadata
) -> None:
    """Fold the SEO fields onto the locale row.

    There is no SEO table any more. ``canonical_path`` and ``robots`` got their
    own columns in migration ``20260812_0109``: before that an editor could set
    ``noindex`` in the console and the page was indexed anyway, because the live
    row had nowhere to carry the directive.
    """

    await session.execute(
        text(
            "UPDATE content_localizations SET seo_title=:title,seo_description=:description,"
            "social_title=:title,social_description=:description,"
            "canonical_path=:canonical_path,robots=CAST(:robots AS jsonb),"
            "cover_media_id=COALESCE(CAST(:og_image AS uuid),cover_media_id),updated_at=now() "
            "WHERE entry_id=:entry_id AND locale=:locale"
        ),
        {
            "entry_id": str(entry_id),
            "locale": locale,
            "title": seo.seo_title,
            "description": seo.seo_description,
            "canonical_path": seo.canonical_path,
            "robots": _json(list(seo.robots)),
            "og_image": _media_uuid(seo.og_image_media_id),
        },
    )


# ---------------------------------------------------------------------------
# Authoring
# ---------------------------------------------------------------------------


async def create_entry(
    session: AsyncSession, *, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    enabled()
    bodies, report = _sanitize_bodies(payload["bodies"])
    default_locale = payload["default_locale"]
    default_body = next((body for body in bodies if body.locale == default_locale), None)
    if default_body is None:
        raise VavError(
            "CMS_DEFAULT_LOCALE_MISSING",
            "The entry must include content in its default locale.",
            status_code=422,
        )
    if len(payload["content_type"]) > ENTRY_TYPE_MAX_LENGTH:
        raise VavError(
            "CMS_CONTENT_TYPE_TOO_LONG",
            f"A content type is limited to {ENTRY_TYPE_MAX_LENGTH} characters.",
            status_code=422,
        )
    seo_raw = next(
        (raw.get("seo") for raw in payload["bodies"] if raw["locale"] == default_locale), None
    )
    try:
        seo = validate_seo_metadata(
            _seo_from_payload(seo_raw, default_body, entry_code=payload["entry_code"])
        )
    except CmsRuleError as error:
        raise _fail(error) from error
    entry_id = uuid4()
    internal_name = (default_body.title or payload["entry_code"]).strip()[:INTERNAL_NAME_MAX_LENGTH]
    try:
        await session.execute(
            text(
                "INSERT INTO content_entries "
                "(id,entry_type,internal_name,canonical_slug,status,default_locale,visibility,author_id,current_version) "
                "VALUES (:id,:content_type,:internal_name,:entry_code,'draft',:default_locale,'public',:actor,1)"
            ),
            {
                "id": str(entry_id),
                "entry_code": payload["entry_code"],
                "content_type": payload["content_type"],
                "internal_name": internal_name,
                "default_locale": default_locale,
                "actor": str(actor_id),
            },
        )
    except IntegrityError as exc:
        # Uniqueness is on (entry_type, canonical_slug): the same code may exist
        # for a page and for an article, but not twice for the same type.
        raise VavError(
            "CMS_ENTRY_CODE_TAKEN", "That entry code already exists.", status_code=409
        ) from exc
    await _replace_locales(session, entry_id=entry_id, bodies=bodies)
    await _write_seo(session, entry_id=entry_id, locale=default_locale, seo=seo)
    revision = await _write_revision(
        session,
        entry_id=entry_id,
        bodies=bodies,
        seo=seo,
        action=RevisionAction.CREATED,
        actor_id=actor_id,
        change_summary="Entry created.",
        sanitizer_report=report,
    )
    await _audit(
        session, entry_id=entry_id, revision_number=revision, action="created", actor_id=actor_id
    )
    return {
        "entry_id": str(entry_id),
        "entry_code": payload["entry_code"],
        "status": EntryStatus.DRAFT.value,
        "revision_number": revision,
        "sanitizer_report": report,
    }


async def update_entry(
    session: AsyncSession, *, entry_id: UUID, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Replace the locale bodies and append a revision.

    A published entry can be edited: the edit lands as a new revision and the
    published one keeps serving until it is republished. That is what makes
    "fix a typo without unpublishing the page" safe.
    """

    enabled()
    entry = await _load_entry(session, entry_id, lock=True)
    bodies, report = _sanitize_bodies(payload["bodies"])
    default_body = next((body for body in bodies if body.locale == entry["default_locale"]), None)
    seo = None
    if default_body is not None:
        seo_raw = next(
            (
                raw.get("seo")
                for raw in payload["bodies"]
                if raw["locale"] == entry["default_locale"]
            ),
            None,
        )
        try:
            seo = validate_seo_metadata(
                _seo_from_payload(seo_raw, default_body, entry_code=entry["entry_code"])
            )
        except CmsRuleError as error:
            raise _fail(error) from error
    # The locale rows carry the SEO columns now, so they have to exist before
    # the SEO write lands on them.
    await _replace_locales(session, entry_id=entry_id, bodies=bodies)
    if seo is not None:
        await _write_seo(session, entry_id=entry_id, locale=entry["default_locale"], seo=seo)
    revision = await _write_revision(
        session,
        entry_id=entry_id,
        bodies=await _load_bodies(session, entry_id),
        seo=seo,
        action=RevisionAction.EDITED,
        actor_id=actor_id,
        change_summary=payload.get("change_note") or "Entry edited.",
        sanitizer_report=report,
    )
    await session.execute(
        text("UPDATE content_entries SET version=version+1,updated_at=now() WHERE id=:id"),
        {"id": str(entry_id)},
    )
    await _audit(
        session,
        entry_id=entry_id,
        revision_number=revision,
        action="edited",
        actor_id=actor_id,
        reason=payload.get("change_note"),
    )
    return {"entry_id": str(entry_id), "revision_number": revision, "sanitizer_report": report}


async def transition_entry(
    session: AsyncSession, *, entry_id: UUID, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Move an entry through the workflow, checking publishability on the way in."""

    enabled()
    now = _now()
    entry = await _load_entry(session, entry_id, lock=True)
    target = payload["target_status"]
    try:
        validate_entry_transition(entry["status"], target)
    except CmsRuleError as error:
        raise _fail(error) from error
    bodies = await _load_bodies(session, entry_id)
    if target in (EntryStatus.PUBLISHED.value, EntryStatus.SCHEDULED.value):
        scheduled_for = payload.get("scheduled_publish_at")
        if target == EntryStatus.SCHEDULED.value and scheduled_for is None:
            raise VavError(
                "CMS_SCHEDULE_REQUIRED",
                "A scheduled publication needs a time.",
                status_code=422,
            )
        try:
            ensure_publishable(
                bodies=bodies,
                default_locale=entry["default_locale"],
                scheduled_for=scheduled_for if target == EntryStatus.SCHEDULED.value else None,
                now=now,
            )
        except CmsRuleError as error:
            raise _fail(error) from error
    revisions = await _load_revisions(session, entry_id)
    head = max((item.revision_number for item in revisions), default=0)
    published_at = now if target == EntryStatus.PUBLISHED.value else None
    # Two different numbers, two different columns. ``published_revision_number``
    # is the revision members are reading; ``current_version`` is the head of
    # history and is maintained by whoever appends a revision, not here.
    # Collapsing them — which this code used to do — made the older content
    # console renumber its next snapshot onto a number that already existed.
    await session.execute(
        text(
            "UPDATE content_entries SET status=:status,"
            "scheduled_publish_at=:scheduled,"
            "published_at=CASE WHEN :status='published' THEN :published_at ELSE published_at END,"
            "published_revision_number=CASE WHEN :status='published' THEN :head "
            "  ELSE published_revision_number END,"
            "published_by=CASE WHEN :status='published' THEN CAST(:actor AS uuid) ELSE published_by END,"
            "archived_at=CASE WHEN :status='archived' THEN now() ELSE NULL END,"
            "version=version+1,updated_at=now() WHERE id=:id"
        ),
        {
            "id": str(entry_id),
            "status": target,
            "scheduled": payload.get("scheduled_publish_at"),
            "published_at": published_at,
            "head": head,
            "actor": str(actor_id),
        },
    )
    if target == EntryStatus.PUBLISHED.value:
        await session.execute(
            text(
                "UPDATE content_localizations SET translation_status='published',updated_at=now() "
                "WHERE entry_id=:entry_id AND translation_status='ready'"
            ),
            {"entry_id": str(entry_id)},
        )
        await _publish_event(
            session,
            "cms.entry.published.v1",
            entry_id,
            {"entry_code": entry["entry_code"], "revision_number": head},
        )
    await _audit(
        session,
        entry_id=entry_id,
        revision_number=head,
        action=target,
        actor_id=actor_id,
        reason=payload.get("reason"),
    )
    return {"entry_id": str(entry_id), "status": target, "revision_number": head}


async def rollback_entry(
    session: AsyncSession, *, entry_id: UUID, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Restore an older revision by appending a new one.

    Nothing between the target and the head is deleted, so the audit trail
    still shows what the page said in the meantime.
    """

    enabled()
    now = _now()
    entry = await _load_entry(session, entry_id, lock=True)
    revisions = await _load_revisions(session, entry_id)
    try:
        plan = plan_rollback(
            revisions, target_revision_number=int(payload["target_revision_number"]), now=now
        )
    except CmsRuleError as error:
        raise _fail(error) from error
    source = (
        (
            await session.execute(
                text(
                    "SELECT snapshot FROM content_versions "
                    "WHERE entry_id=:entry_id AND version_number=:number"
                ),
                {"entry_id": str(entry_id), "number": plan.source_revision_number},
            )
        )
        .mappings()
        .first()
    )
    if source is None:
        raise VavError("CMS_REVISION_NOT_FOUND", "Revision not found.", status_code=404)
    snapshot = source["snapshot"] if isinstance(source["snapshot"], dict) else {}
    bodies = _bodies_from_snapshot(snapshot.get("locales"), sanitize=True)
    if not bodies:
        raise VavError(
            "CMS_REVISION_NOT_RESTORABLE",
            "That revision carries no locale content to restore.",
            status_code=422,
        )
    seo = _seo_from_snapshot(snapshot.get("seo"))
    await _replace_locales(session, entry_id=entry_id, bodies=bodies)
    if seo is not None:
        await _write_seo(session, entry_id=entry_id, locale=entry["default_locale"], seo=seo)
    revision = await _write_revision(
        session,
        entry_id=entry_id,
        bodies=bodies,
        seo=seo,
        action=RevisionAction.ROLLED_BACK,
        actor_id=actor_id,
        change_summary=payload["reason"],
        source_revision_number=plan.source_revision_number,
    )
    await _audit(
        session,
        entry_id=entry_id,
        revision_number=revision,
        action="rolled_back",
        actor_id=actor_id,
        reason=payload["reason"],
    )
    return {
        "entry_id": str(entry_id),
        "revision_number": revision,
        "restored_from": plan.source_revision_number,
    }


async def list_revisions(session: AsyncSession, *, entry_id: UUID) -> dict[str, Any]:
    enabled()
    rows = (
        (
            await session.execute(
                text(
                    "SELECT version_number,snapshot,created_by,created_at FROM content_versions "
                    "WHERE entry_id=:entry_id ORDER BY version_number DESC"
                ),
                {"entry_id": str(entry_id)},
            )
        )
        .mappings()
        .all()
    )
    items: list[dict[str, Any]] = []
    for row in rows:
        snapshot = row["snapshot"] if isinstance(row["snapshot"], dict) else {}
        items.append(
            {
                "revision_number": int(row["version_number"]),
                "action": snapshot.get("action") or RevisionAction.EDITED.value,
                "source_revision_number": snapshot.get("source_revision_number"),
                "content_hash": snapshot.get("content_hash"),
                "author_id": str(row["created_by"]) if row["created_by"] else None,
                "created_at": row["created_at"],
                "sanitizer_report": snapshot.get("sanitizer_report") or {},
            }
        )
    return {"items": items}


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_revision(token: str) -> int | None:
    """Read the pinned revision out of a preview token.

    ``content_preview_tokens`` has no revision column, so the revision travels
    in the token. That is not a place to hide a secret and it is not treated as
    one: the stored hash covers the whole token, so a token whose revision
    prefix was edited simply does not match any row.
    """

    head, separator, _ = token.partition(".")
    if not separator or not head.isdigit():
        return None
    return int(head)


async def grant_preview(
    session: AsyncSession, *, entry_id: UUID, actor_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Issue a time-boxed preview link pinned to one revision.

    Only the hash of the token is stored, so a database read cannot be turned
    into a working preview link for unpublished content.
    """

    enabled()
    now = _now()
    revisions = await _load_revisions(session, entry_id)
    head = max((item.revision_number for item in revisions), default=0)
    revision_number = int(payload.get("revision_number") or head)
    try:
        claim = build_preview_claim(
            entry_id=str(entry_id),
            revision_number=revision_number,
            issued_at=now,
            ttl_minutes=int(payload["ttl_minutes"]),
            audience=payload["audience"],
        )
    except CmsRuleError as error:
        raise _fail(error) from error
    token = f"{claim.revision_number}.{secrets.token_urlsafe(32)}"
    await session.execute(
        text(
            "INSERT INTO content_preview_tokens (entry_id,token_hash,locale,created_by,expires_at) "
            "VALUES (:entry_id,:token_hash,:locale,:actor,:expires_at)"
        ),
        {
            "entry_id": str(entry_id),
            "token_hash": _hash_token(token),
            "locale": payload.get("locale"),
            "actor": str(actor_id),
            "expires_at": claim.expires_at,
        },
    )
    return {
        "preview_token": token,
        "revision_number": claim.revision_number,
        "expires_at": claim.expires_at.isoformat(),
    }


async def read_preview(session: AsyncSession, *, token: str, locale: str) -> dict[str, Any]:
    """Render a pinned revision, drafts included, with the fallback marker."""

    enabled()
    now = _now()
    revision_number = _token_revision(token)
    if revision_number is None:
        raise VavError("CMS_PREVIEW_NOT_FOUND", "Preview link not found.", status_code=404)
    row = (
        (
            await session.execute(
                text(
                    "SELECT t.entry_id,t.expires_at,t.revoked_at,v.version_number,v.snapshot,"
                    "e.canonical_slug,e.default_locale "
                    "FROM content_preview_tokens t "
                    "JOIN content_entries e ON e.id=t.entry_id "
                    "LEFT JOIN content_versions v ON v.entry_id=t.entry_id AND v.version_number=:revision_number "
                    "WHERE t.token_hash=:token_hash"
                ),
                {"token_hash": _hash_token(token), "revision_number": revision_number},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise VavError("CMS_PREVIEW_NOT_FOUND", "Preview link not found.", status_code=404)
    if row["revoked_at"] is not None and row["revoked_at"] <= now:
        raise VavError(
            "CMS_PREVIEW_REVOKED", "This preview link has been revoked.", status_code=410
        )
    if now >= row["expires_at"]:
        raise VavError("CMS_PREVIEW_EXPIRED", "This preview link has expired.", status_code=410)
    if row["snapshot"] is None:
        raise VavError("CMS_REVISION_NOT_FOUND", "Revision not found.", status_code=404)
    snapshot = row["snapshot"] if isinstance(row["snapshot"], dict) else {}
    bodies = _bodies_from_snapshot(snapshot.get("locales"))
    try:
        resolved = resolve_localization(
            bodies,
            requested_locale=locale,
            default_locale=row["default_locale"],
            published_only=False,
        )
    except CmsRuleError as error:
        raise _fail(error, status_code=404) from error
    return {
        "entry_code": row["canonical_slug"],
        "revision_number": int(row["version_number"]),
        "preview": True,
        **resolved.as_dict(),
    }


async def revoke_preview(
    session: AsyncSession, *, grant_id: UUID, actor_id: UUID
) -> dict[str, Any]:
    """Revoke a preview link.

    ``content_preview_tokens`` records *when* a link was revoked but not by
    whom, so the actor is recorded in the platform audit log instead.
    """

    enabled()
    await session.execute(
        text("UPDATE content_preview_tokens SET revoked_at=now() WHERE id=:id"),
        {"id": str(grant_id)},
    )
    await session.execute(
        text(
            "INSERT INTO audit_events (actor_id,actor_type,action,subject_type,subject_id,context,occurred_at) "
            "VALUES (:actor,'administrator','cms.preview.revoked','content_preview_token',:id,'{}'::jsonb,now())"
        ),
        {"actor": str(actor_id) if actor_id else None, "id": str(grant_id)},
    )
    return {"grant_id": str(grant_id), "revoked": True}


# ---------------------------------------------------------------------------
# Public read
# ---------------------------------------------------------------------------


async def read_public_entry(
    session: AsyncSession, *, entry_code: str, locale: str
) -> dict[str, Any]:
    """Serve published content, stating which locale was actually served.

    When the requested translation is missing the default-locale body is
    returned with ``translation_fallback: true`` and the reason, rather than
    silently showing the wrong language.
    """

    enabled()
    now = _now()
    entry = (
        (
            await session.execute(
                text(
                    "SELECT id,canonical_slug,entry_type,status,default_locale,published_at,"
                    "published_revision_number,current_version FROM content_entries "
                    "WHERE canonical_slug=:entry_code AND visibility='public' "
                    "ORDER BY (status='published') DESC,published_at DESC NULLS LAST LIMIT 1"
                ),
                {"entry_code": entry_code},
            )
        )
        .mappings()
        .first()
    )
    if entry is None or not is_entry_member_visible(
        entry["status"], published_at=entry["published_at"], now=now
    ):
        # 404 rather than 403: an unpublished entry is indistinguishable from
        # one that does not exist.
        raise VavError("CMS_ENTRY_NOT_FOUND", "Content entry not found.", status_code=404)
    bodies = await _load_bodies(session, UUID(str(entry["id"])))
    try:
        resolved = resolve_localization(
            bodies,
            requested_locale=locale,
            default_locale=entry["default_locale"],
            published_only=True,
        )
    except CmsRuleError as error:
        raise _fail(error, status_code=404) from error
    seo_row = (
        (
            await session.execute(
                text(
                    "SELECT seo_title,seo_description,social_title,social_description,"
                    "canonical_path,robots,cover_media_id "
                    "FROM content_localizations WHERE entry_id=:entry_id AND locale=:locale"
                ),
                {"entry_id": str(entry["id"]), "locale": resolved.served_locale},
            )
        )
        .mappings()
        .first()
    )
    seo: dict[str, Any] | None = None
    if seo_row is not None and (seo_row["seo_title"] or seo_row["seo_description"]):
        seo = {
            "seo_title": seo_row["seo_title"],
            "seo_description": seo_row["seo_description"],
            "social_title": seo_row["social_title"],
            "social_description": seo_row["social_description"],
            "og_image_media_id": (
                str(seo_row["cover_media_id"]) if seo_row["cover_media_id"] else None
            ),
            # An editor-set canonical wins; the derived path is only the
            # fallback for a row that predates migration 0109.
            "canonical_path": (seo_row["canonical_path"] or f"/content/{entry['canonical_slug']}"),
            "robots": list(seo_row["robots"] or ["index", "follow"]),
        }
    return {
        "entry_code": entry["canonical_slug"],
        "content_type": entry["entry_type"],
        "published_at": entry["published_at"].isoformat() if entry["published_at"] else None,
        # What the member is actually reading. The head falls back in only for
        # rows written before migration 0110, where the two were the same
        # number by construction.
        "revision_number": entry["published_revision_number"] or entry["current_version"],
        "seo": seo,
        **resolved.as_dict(),
    }


async def list_public_entries(
    session: AsyncSession, *, content_type: str | None, locale: str, limit: int, offset: int
) -> dict[str, Any]:
    enabled()
    now = _now()
    rows = (
        (
            await session.execute(
                text(
                    "SELECT e.canonical_slug,e.entry_type,e.published_at,e.default_locale,"
                    "COALESCE(l.title, ldef.title) AS title,"
                    "COALESCE(l.excerpt, ldef.excerpt) AS summary,"
                    "(l.title IS NULL) AS translation_fallback "
                    "FROM content_entries e "
                    "LEFT JOIN content_localizations l ON l.entry_id=e.id AND l.locale=:locale AND l.translation_status='published' "
                    "LEFT JOIN content_localizations ldef ON ldef.entry_id=e.id AND ldef.locale=e.default_locale AND ldef.translation_status='published' "
                    "WHERE e.status='published' AND e.visibility='public' AND e.published_at <= :now "
                    "AND (:content_type IS NULL OR e.entry_type=:content_type) "
                    "AND COALESCE(l.title, ldef.title) IS NOT NULL "
                    "ORDER BY e.published_at DESC LIMIT :limit OFFSET :offset"
                ),
                {
                    "locale": locale,
                    "now": now,
                    "content_type": content_type,
                    "limit": limit,
                    "offset": offset,
                },
            )
        )
        .mappings()
        .all()
    )
    return {
        "items": [
            {
                "entry_code": row["canonical_slug"],
                "content_type": row["entry_type"],
                "title": row["title"],
                "summary": row["summary"] or "",
                "published_at": row["published_at"].isoformat() if row["published_at"] else None,
                "requested_locale": locale,
                "served_locale": locale
                if not row["translation_fallback"]
                else row["default_locale"],
                "translation_fallback": bool(row["translation_fallback"]),
            }
            for row in rows
        ]
    }


# ---------------------------------------------------------------------------
# Editor helpers
# ---------------------------------------------------------------------------


def preview_sanitizer(payload: dict[str, Any]) -> dict[str, Any]:
    """Dry-run the sanitizer so an editor sees exactly what will be stripped."""

    try:
        cleaned = sanitize_rich_text(payload["body_html"])
    except CmsRuleError as error:
        raise _fail(error) from error
    return {
        "body_html": cleaned.html,
        "plain_text": cleaned.plain_text,
        "removed_tags": list(cleaned.removed_tags),
        "removed_attributes": list(cleaned.removed_attributes),
        "was_modified": cleaned.was_modified,
    }


async def translation_coverage(session: AsyncSession) -> dict[str, Any]:
    """Which entries are published in which locales - the fallback backlog."""

    enabled()
    rows = (
        (
            await session.execute(
                text(
                    "SELECT e.canonical_slug,e.default_locale,"
                    "array_agg(l.locale ORDER BY l.locale) FILTER (WHERE l.translation_status='published') AS published_locales "
                    "FROM content_entries e LEFT JOIN content_localizations l ON l.entry_id=e.id "
                    "WHERE e.status='published' GROUP BY e.id,e.canonical_slug,e.default_locale "
                    "ORDER BY e.canonical_slug"
                )
            )
        )
        .mappings()
        .all()
    )
    return {
        "items": [
            {
                "entry_code": row["canonical_slug"],
                "default_locale": row["default_locale"],
                "published_locales": list(row["published_locales"] or []),
                "missing_locales": [
                    locale
                    for locale in get_settings().cms_supported_locales
                    if locale not in (row["published_locales"] or [])
                ],
            }
            for row in rows
        ]
    }
