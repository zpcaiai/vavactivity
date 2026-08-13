"""Pure bilingual CMS rules: sanitizing, fallback, SEO, revisions (CMS-001).

Three decisions this file makes explicit rather than leaving to the frontend:

* **Sanitizing is server-side and allow-list based.** :func:`sanitize_rich_text`
  keeps a named set of tags and attributes and drops everything else, including
  the content of ``script`` and ``style``. A deny-list would be one novel
  vector away from an XSS; an allow-list is wrong only in the safe direction.
* **A missing translation is announced, never faked.** :func:`resolve_localization`
  returns the default-locale content together with ``translation_fallback=True``
  and the locale actually served, so the client can label it. Silently showing
  Chinese to a member who asked for English, with no marker, is the failure this
  rule exists to prevent.
* **History is append-only.** A rollback writes a *new* revision whose body is a
  copy of an old one (:func:`plan_rollback`); it never deletes the revisions in
  between, so "what did the page say last Tuesday" always has an answer.

No database, settings, network or clock access: ``now`` is always an argument.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from html import escape, unescape
from html.parser import HTMLParser
from typing import Any


class CmsRuleError(Exception):
    """Raised when a caller violates a content-publishing rule."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, object] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, object] = dict(details or {})


def _require_aware(**values: datetime | None) -> None:
    for label, value in values.items():
        if value is not None and value.tzinfo is None:
            raise CmsRuleError("CMS_NAIVE_DATETIME", f"{label} must be timezone-aware.")


# ---------------------------------------------------------------------------
# Rich-text sanitizer
# ---------------------------------------------------------------------------

#: Tags an editor may use. Anything absent is unwrapped: the tag disappears and
#: its text survives, escaped. That keeps a stray ``<div>`` from eating a
#: paragraph while still refusing to render it.
ALLOWED_TAGS: frozenset[str] = frozenset(
    {
        "p",
        "br",
        "hr",
        "strong",
        "b",
        "em",
        "i",
        "u",
        "s",
        "ul",
        "ol",
        "li",
        "blockquote",
        "h2",
        "h3",
        "h4",
        "a",
        "img",
        "figure",
        "figcaption",
        "code",
        "pre",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
    }
)

#: Tags whose *content* is dropped as well as the tag. Unwrapping a ``script``
#: would paste its source into the page as visible text; worse, unwrapping a
#: ``style`` can re-enable CSS-based exfiltration in some renderers.
DROPPED_SUBTREE_TAGS: frozenset[str] = frozenset(
    {"script", "style", "iframe", "object", "embed", "template", "noscript", "svg", "math"}
)

ALLOWED_ATTRIBUTES: Mapping[str, frozenset[str]] = {
    "a": frozenset({"href", "title", "rel", "target"}),
    "img": frozenset({"src", "alt", "title", "width", "height"}),
    "td": frozenset({"colspan", "rowspan"}),
    "th": frozenset({"colspan", "rowspan", "scope"}),
}

#: URL schemes an attribute may carry. ``data:`` is absent on purpose: a
#: ``data:text/html`` URL is a same-origin script in a link.
ALLOWED_URL_SCHEMES: frozenset[str] = frozenset({"http", "https", "mailto", "tel"})

_URL_ATTRIBUTES: frozenset[str] = frozenset({"href", "src"})
_VOID_TAGS: frozenset[str] = frozenset({"br", "hr", "img"})


def _is_safe_url(value: str) -> bool:
    """Reject anything that could execute, after normalizing the evasions.

    Entity encoding (``&#106;avascript:``), embedded control characters
    (``java\\tscript:``) and leading whitespace are all normalized away before
    the scheme is inspected, because each of them is a documented filter
    bypass.
    """

    cleaned = unescape(value)
    cleaned = "".join(character for character in cleaned if ord(character) > 0x20)
    if not cleaned:
        return False
    lowered = cleaned.lower()
    if lowered.startswith("//"):
        # Protocol-relative: inherits the page scheme and points off-site.
        return False
    if lowered.startswith(("/", "#", "?", "./", "../")):
        return True
    head = lowered.split("/", 1)[0]
    if ":" not in head:
        return True  # a relative path such as "articles/2026/spring"
    scheme = head.split(":", 1)[0]
    return scheme in ALLOWED_URL_SCHEMES


class _Sanitizer(HTMLParser):
    """Allow-list HTML rewriter. Emits balanced, escaped output only."""

    def __init__(
        self,
        *,
        allowed_tags: frozenset[str],
        allowed_attributes: Mapping[str, frozenset[str]],
    ) -> None:
        super().__init__(convert_charrefs=True)
        self._allowed_tags = allowed_tags
        self._allowed_attributes = allowed_attributes
        self._out: list[str] = []
        self._open: list[str] = []
        self._drop_depth = 0
        self.removed_tags: set[str] = set()
        self.removed_attributes: set[str] = set()

    # -- helpers ---------------------------------------------------------
    def _render_attributes(self, tag: str, attrs: Sequence[tuple[str, str | None]]) -> str:
        allowed = self._allowed_attributes.get(tag, frozenset())
        rendered: list[str] = []
        for raw_name, raw_value in attrs:
            name = (raw_name or "").lower()
            value = raw_value or ""
            if name.startswith("on") or name not in allowed:
                # Every ``on*`` handler is refused by name, so a future
                # ``onwhatever`` attribute is blocked before it is invented.
                self.removed_attributes.add(f"{tag}@{name}")
                continue
            if name in _URL_ATTRIBUTES and not _is_safe_url(value):
                self.removed_attributes.add(f"{tag}@{name}")
                continue
            rendered.append(f'{name}="{escape(value, quote=True)}"')
        if tag == "a":
            has_blank_target = any(
                (name or "").lower() == "target" and (value or "").lower() == "_blank"
                for name, value in attrs
            )
            if has_blank_target and not any(item.startswith("rel=") for item in rendered):
                rendered.append('rel="noopener noreferrer"')
        return "" if not rendered else " " + " ".join(rendered)

    # -- HTMLParser hooks ------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in DROPPED_SUBTREE_TAGS:
            self._drop_depth += 1
            self.removed_tags.add(tag)
            return
        if self._drop_depth:
            return
        if tag not in self._allowed_tags:
            self.removed_tags.add(tag)
            return
        self._out.append(f"<{tag}{self._render_attributes(tag, attrs)}>")
        if tag not in _VOID_TAGS:
            self._open.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in DROPPED_SUBTREE_TAGS:
            self.removed_tags.add(tag)
            return
        if self._drop_depth:
            return
        if tag not in self._allowed_tags:
            self.removed_tags.add(tag)
            return
        self._out.append(f"<{tag}{self._render_attributes(tag, attrs)}>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in DROPPED_SUBTREE_TAGS:
            self._drop_depth = max(0, self._drop_depth - 1)
            return
        if self._drop_depth or tag in _VOID_TAGS:
            return
        if tag in self._open:
            # Close everything the document left open inside this element, so
            # the output is balanced even when the input was not.
            while self._open:
                current = self._open.pop()
                self._out.append(f"</{current}>")
                if current == tag:
                    break

    def handle_data(self, data: str) -> None:
        if self._drop_depth:
            return
        self._out.append(escape(data, quote=False))

    def handle_comment(self, data: str) -> None:
        # Conditional comments are executable in some legacy renderers.
        return

    def unknown_decl(self, data: str) -> None:
        return

    def handle_decl(self, decl: str) -> None:
        return

    def handle_pi(self, data: str) -> None:
        return

    def result(self) -> str:
        tail = "".join(f"</{tag}>" for tag in reversed(self._open))
        self._open.clear()
        return "".join(self._out) + tail


@dataclass(frozen=True)
class SanitizedContent:
    html: str
    plain_text: str
    removed_tags: tuple[str, ...]
    removed_attributes: tuple[str, ...]

    @property
    def was_modified(self) -> bool:
        return bool(self.removed_tags or self.removed_attributes)


def sanitize_rich_text(
    html: str,
    *,
    allowed_tags: frozenset[str] = ALLOWED_TAGS,
    allowed_attributes: Mapping[str, frozenset[str]] = ALLOWED_ATTRIBUTES,
    max_length: int = 200_000,
) -> SanitizedContent:
    """Return an allow-listed, balanced, escaped copy of ``html``.

    The sanitizer runs on **write**, and the sanitized text is what is stored.
    Sanitizing on read would leave the raw payload in the database for any
    other consumer - an export, a search indexer, an email renderer - to
    faithfully reproduce.
    """

    if len(html) > max_length:
        raise CmsRuleError(
            "CMS_BODY_TOO_LONG",
            f"Rich text is limited to {max_length} characters.",
            details={"length": len(html), "max_length": max_length},
        )
    parser = _Sanitizer(allowed_tags=allowed_tags, allowed_attributes=allowed_attributes)
    parser.feed(html)
    parser.close()
    cleaned = parser.result()
    return SanitizedContent(
        html=cleaned,
        plain_text=extract_plain_text(cleaned),
        removed_tags=tuple(sorted(parser.removed_tags)),
        removed_attributes=tuple(sorted(parser.removed_attributes)),
    )


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in ("br", "p", "li", "tr", "h2", "h3", "h4"):
            self.parts.append(" ")


def extract_plain_text(html: str) -> str:
    """Flatten sanitized HTML for search indexing and SEO description defaults."""

    extractor = _TextExtractor()
    extractor.feed(html)
    extractor.close()
    return " ".join("".join(extractor.parts).split())


# ---------------------------------------------------------------------------
# Bilingual content and the documented fallback
# ---------------------------------------------------------------------------

#: The locale a fallback lands on when a requested translation is missing.
#: Overridable per entry; this is only the platform-wide default.
DEFAULT_LOCALE = "zh-CN"

#: The locales the bilingual workflow is built around. An entry may carry more.
SUPPORTED_LOCALES: tuple[str, ...] = ("zh-CN", "en-US")


class LocaleStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    PUBLISHED = "published"


@dataclass(frozen=True)
class LocalizedBody:
    locale: str
    title: str
    body_html: str
    summary: str = ""
    status: LocaleStatus = LocaleStatus.DRAFT


@dataclass(frozen=True)
class ResolvedContent:
    """What a reader actually gets, plus an honest account of what it is."""

    requested_locale: str
    served_locale: str
    #: ``True`` whenever the requested translation was unavailable. The client
    #: must surface this; it is the whole point of the rule.
    translation_fallback: bool
    fallback_reason: str | None
    body: LocalizedBody
    available_locales: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "requested_locale": self.requested_locale,
            "served_locale": self.served_locale,
            "translation_fallback": self.translation_fallback,
            "fallback_reason": self.fallback_reason,
            "available_locales": list(self.available_locales),
            "locale": self.body.locale,
            "title": self.body.title,
            "summary": self.body.summary,
            "body_html": self.body.body_html,
        }


def resolve_localization(
    bodies: Sequence[LocalizedBody],
    *,
    requested_locale: str,
    default_locale: str = DEFAULT_LOCALE,
    published_only: bool = True,
) -> ResolvedContent:
    """Serve a locale, falling back to the default with an explicit marker.

    Resolution order, and the reason recorded for each step:

    1. the requested locale, if present and visible -> no fallback
    2. the same language with a different region (``en-GB`` -> ``en-US``) ->
       ``locale_region_fallback``
    3. the entry's default locale -> ``default_locale_fallback``
    4. nothing visible at all -> ``CMS_TRANSLATION_MISSING``

    Step 4 raises rather than returning an empty string: a blank page with a
    200 status is indistinguishable from real content that happens to be short.
    """

    visible = [
        body for body in bodies if not published_only or body.status is LocaleStatus.PUBLISHED
    ]
    available = tuple(sorted(body.locale for body in visible))
    by_locale = {body.locale: body for body in visible}
    exact = by_locale.get(requested_locale)
    if exact is not None:
        return ResolvedContent(
            requested_locale=requested_locale,
            served_locale=exact.locale,
            translation_fallback=False,
            fallback_reason=None,
            body=exact,
            available_locales=available,
        )
    language = requested_locale.split("-", 1)[0].lower()
    for body in sorted(visible, key=lambda item: item.locale):
        if body.locale.split("-", 1)[0].lower() == language:
            return ResolvedContent(
                requested_locale=requested_locale,
                served_locale=body.locale,
                translation_fallback=True,
                fallback_reason="locale_region_fallback",
                body=body,
                available_locales=available,
            )
    fallback = by_locale.get(default_locale)
    if fallback is not None:
        return ResolvedContent(
            requested_locale=requested_locale,
            served_locale=fallback.locale,
            translation_fallback=True,
            fallback_reason="default_locale_fallback",
            body=fallback,
            available_locales=available,
        )
    raise CmsRuleError(
        "CMS_TRANSLATION_MISSING",
        "Neither the requested locale nor the default locale is available for this entry.",
        details={
            "requested_locale": requested_locale,
            "default_locale": default_locale,
            "available_locales": list(available),
        },
    )


# ---------------------------------------------------------------------------
# Publishing workflow
# ---------------------------------------------------------------------------


class EntryStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    ARCHIVED = "archived"


_ENTRY_TRANSITIONS: Mapping[EntryStatus, frozenset[EntryStatus]] = {
    EntryStatus.DRAFT: frozenset({EntryStatus.IN_REVIEW, EntryStatus.ARCHIVED}),
    EntryStatus.IN_REVIEW: frozenset(
        {EntryStatus.DRAFT, EntryStatus.SCHEDULED, EntryStatus.PUBLISHED, EntryStatus.ARCHIVED}
    ),
    EntryStatus.SCHEDULED: frozenset(
        {EntryStatus.PUBLISHED, EntryStatus.IN_REVIEW, EntryStatus.ARCHIVED}
    ),
    # A published entry is unpublished by archiving it, or edited by going back
    # to draft; the published revision stays readable either way.
    EntryStatus.PUBLISHED: frozenset({EntryStatus.DRAFT, EntryStatus.ARCHIVED}),
    EntryStatus.ARCHIVED: frozenset({EntryStatus.DRAFT}),
}

MEMBER_VISIBLE_ENTRY_STATUSES: frozenset[EntryStatus] = frozenset({EntryStatus.PUBLISHED})


def validate_entry_transition(current: str, target: str) -> None:
    try:
        current_status = EntryStatus(current)
        target_status = EntryStatus(target)
    except ValueError as exc:
        raise CmsRuleError("CMS_STATUS_UNKNOWN", f"Unknown content status: {exc}") from exc
    if target_status not in _ENTRY_TRANSITIONS[current_status]:
        raise CmsRuleError(
            "CMS_TRANSITION_INVALID",
            f"Cannot move content entry from {current_status} to {target_status}.",
            details={"current": current_status.value, "target": target_status.value},
        )


def is_entry_member_visible(status: str, *, published_at: datetime | None, now: datetime) -> bool:
    """Scheduled means scheduled: a future ``published_at`` is not yet public."""

    _require_aware(published_at=published_at, now=now)
    try:
        entry_status = EntryStatus(status)
    except ValueError:
        return False
    if entry_status not in MEMBER_VISIBLE_ENTRY_STATUSES:
        return False
    return published_at is not None and published_at <= now


def ensure_publishable(
    *,
    bodies: Sequence[LocalizedBody],
    default_locale: str = DEFAULT_LOCALE,
    seo: SeoMetadata | None = None,
    scheduled_for: datetime | None = None,
    now: datetime,
) -> None:
    """Refuse to publish an entry whose fallback locale is missing or empty.

    Without this check the fallback rule has nothing to fall back *to*, and a
    member requesting a missing translation would get a 422 on a page that is
    supposedly live.
    """

    _require_aware(scheduled_for=scheduled_for, now=now)
    default_body = next((body for body in bodies if body.locale == default_locale), None)
    if default_body is None:
        raise CmsRuleError(
            "CMS_DEFAULT_LOCALE_MISSING",
            "An entry cannot be published without content in its default locale.",
            details={"default_locale": default_locale},
        )
    if not default_body.title.strip() or not extract_plain_text(default_body.body_html).strip():
        raise CmsRuleError(
            "CMS_DEFAULT_LOCALE_EMPTY",
            "The default-locale content must have a title and a non-empty body.",
            details={"default_locale": default_locale},
        )
    if scheduled_for is not None and scheduled_for <= now:
        raise CmsRuleError(
            "CMS_SCHEDULE_IN_PAST", "A scheduled publication time must be in the future."
        )
    if seo is not None:
        validate_seo_metadata(seo)


# ---------------------------------------------------------------------------
# SEO metadata
# ---------------------------------------------------------------------------

SEO_TITLE_MAX = 70
SEO_DESCRIPTION_MAX = 160
ALLOWED_ROBOTS_DIRECTIVES: frozenset[str] = frozenset(
    {"index", "noindex", "follow", "nofollow", "noarchive", "nosnippet"}
)


@dataclass(frozen=True)
class SeoMetadata:
    seo_title: str
    seo_description: str
    canonical_path: str
    robots: tuple[str, ...] = ("index", "follow")
    og_image_media_id: str | None = None


def validate_seo_metadata(seo: SeoMetadata) -> SeoMetadata:
    """Bound the fields search engines truncate, and keep canonicals internal."""

    if not seo.seo_title.strip():
        raise CmsRuleError("CMS_SEO_TITLE_REQUIRED", "An SEO title is required.")
    if len(seo.seo_title) > SEO_TITLE_MAX:
        raise CmsRuleError(
            "CMS_SEO_TITLE_TOO_LONG",
            f"The SEO title is limited to {SEO_TITLE_MAX} characters.",
            details={"length": len(seo.seo_title)},
        )
    if len(seo.seo_description) > SEO_DESCRIPTION_MAX:
        raise CmsRuleError(
            "CMS_SEO_DESCRIPTION_TOO_LONG",
            f"The SEO description is limited to {SEO_DESCRIPTION_MAX} characters.",
            details={"length": len(seo.seo_description)},
        )
    if not seo.canonical_path.startswith("/") or seo.canonical_path.startswith("//"):
        raise CmsRuleError(
            "CMS_CANONICAL_NOT_RELATIVE",
            "A canonical path must be site-relative.",
            details={"canonical_path": seo.canonical_path},
        )
    unknown = [directive for directive in seo.robots if directive not in ALLOWED_ROBOTS_DIRECTIVES]
    if unknown:
        raise CmsRuleError(
            "CMS_ROBOTS_DIRECTIVE_UNKNOWN",
            "An unknown robots directive was supplied.",
            details={"directives": unknown},
        )
    if "index" in seo.robots and "noindex" in seo.robots:
        raise CmsRuleError(
            "CMS_ROBOTS_DIRECTIVE_CONFLICT", "robots cannot be both index and noindex."
        )
    return seo


def derive_seo_defaults(body: LocalizedBody, *, canonical_path: str) -> SeoMetadata:
    """Fill SEO fields from the content itself, truncated at word boundaries."""

    plain = extract_plain_text(body.body_html)
    description = body.summary.strip() or plain
    if len(description) > SEO_DESCRIPTION_MAX:
        description = description[:SEO_DESCRIPTION_MAX].rsplit(" ", 1)[0]
    return SeoMetadata(
        seo_title=body.title[:SEO_TITLE_MAX],
        seo_description=description,
        canonical_path=canonical_path,
    )


# ---------------------------------------------------------------------------
# Revisions and rollback
# ---------------------------------------------------------------------------


class RevisionAction(StrEnum):
    CREATED = "created"
    EDITED = "edited"
    PUBLISHED = "published"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True)
class Revision:
    revision_number: int
    content_hash: str
    action: RevisionAction
    created_at: datetime
    source_revision_number: int | None = None
    locales: tuple[str, ...] = ()


def next_revision_number(revisions: Iterable[Revision]) -> int:
    return max((revision.revision_number for revision in revisions), default=0) + 1


@dataclass(frozen=True)
class RollbackPlan:
    new_revision_number: int
    source_revision_number: int
    content_hash: str


def plan_rollback(
    revisions: Sequence[Revision], *, target_revision_number: int, now: datetime
) -> RollbackPlan:
    """Roll forward to an old body. History is never rewritten.

    Rolling back to the current head is refused rather than silently creating a
    duplicate revision, because a no-op rollback in an audit trail reads like a
    change nobody can explain.
    """

    _require_aware(now=now)
    if not revisions:
        raise CmsRuleError("CMS_REVISION_NOT_FOUND", "This entry has no revisions.")
    target = next(
        (item for item in revisions if item.revision_number == target_revision_number), None
    )
    if target is None:
        raise CmsRuleError(
            "CMS_REVISION_NOT_FOUND",
            "The requested revision does not exist for this entry.",
            details={"revision_number": target_revision_number},
        )
    head = max(revisions, key=lambda item: item.revision_number)
    if head.revision_number == target_revision_number:
        raise CmsRuleError(
            "CMS_ROLLBACK_NO_OP",
            "The requested revision is already the current one.",
            details={"revision_number": target_revision_number},
        )
    return RollbackPlan(
        new_revision_number=next_revision_number(revisions),
        source_revision_number=target_revision_number,
        content_hash=target.content_hash,
    )


def content_fingerprint(bodies: Sequence[LocalizedBody], seo: SeoMetadata | None = None) -> str:
    """Stable hash over every locale plus SEO, used to detect silent edits."""

    import hashlib

    digest = hashlib.sha256()
    for body in sorted(bodies, key=lambda item: item.locale):
        for part in (body.locale, body.title, body.summary, body.body_html, body.status.value):
            digest.update(part.encode("utf-8"))
            digest.update(b"\x00")
    if seo is not None:
        for part in (
            seo.seo_title,
            seo.seo_description,
            seo.canonical_path,
            ",".join(seo.robots),
            seo.og_image_media_id or "",
        ):
            digest.update(part.encode("utf-8"))
            digest.update(b"\x00")
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PreviewClaim:
    entry_id: str
    revision_number: int
    issued_at: datetime
    expires_at: datetime
    audience: str = "internal"
    extra: Mapping[str, Any] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "revision_number": self.revision_number,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "audience": self.audience,
            **dict(self.extra),
        }


def build_preview_claim(
    *,
    entry_id: str,
    revision_number: int,
    issued_at: datetime,
    ttl_minutes: int,
    audience: str = "internal",
) -> PreviewClaim:
    """Describe a preview grant. Signing is the service's job, not this file's.

    The claim is pinned to a *revision*, not to an entry: a reviewer who
    approves what they saw must not have approved whatever the page became
    while the link was open.
    """

    _require_aware(issued_at=issued_at)
    if ttl_minutes < 1:
        raise CmsRuleError("CMS_PREVIEW_TTL_INVALID", "A preview link must live for a minute.")
    if revision_number < 1:
        raise CmsRuleError("CMS_REVISION_NUMBER_INVALID", "Revision numbers start at 1.")
    from datetime import timedelta

    return PreviewClaim(
        entry_id=entry_id,
        revision_number=revision_number,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(minutes=ttl_minutes),
        audience=audience,
    )


def ensure_preview_valid(
    claim: PreviewClaim, *, now: datetime, revoked_at: datetime | None
) -> None:
    _require_aware(now=now, revoked_at=revoked_at)
    if revoked_at is not None and revoked_at <= now:
        raise CmsRuleError("CMS_PREVIEW_REVOKED", "This preview link has been revoked.")
    if now >= claim.expires_at:
        raise CmsRuleError("CMS_PREVIEW_EXPIRED", "This preview link has expired.")
