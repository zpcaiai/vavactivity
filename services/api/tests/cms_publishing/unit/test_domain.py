"""Pure-domain tests for bilingual CMS publishing (B19 part 2 / CMS-001).

The two load-bearing behaviours have named tests below: a missing translation
falls back to the default locale *with an explicit marker*, and rich text is
sanitized against an allow-list that a list of real XSS vectors cannot get past.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from vav.modules.cms_publishing.domain import (
    ALLOWED_TAGS,
    ALLOWED_URL_SCHEMES,
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
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
    ensure_preview_valid,
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

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def _body(
    locale: str, *, title: str = "Title", status: LocaleStatus = LocaleStatus.PUBLISHED
) -> LocalizedBody:
    return LocalizedBody(
        locale=locale,
        title=f"{title} {locale}",
        body_html=f"<p>Body in {locale}</p>",
        summary=f"Summary {locale}",
        status=status,
    )


def _seo(**overrides: object) -> SeoMetadata:
    kwargs: dict[str, object] = {
        "seo_title": "A page title",
        "seo_description": "A short description of the page.",
        "canonical_path": "/articles/a-page",
    }
    kwargs.update(overrides)
    return SeoMetadata(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# XSS sanitizer
# ---------------------------------------------------------------------------

XSS_VECTORS = [
    "<script>alert(1)</script>",
    "<SCRIPT SRC=//evil.example/x.js></SCRIPT>",
    "<img src=x onerror=alert(1)>",
    "<svg/onload=alert(1)>",
    "<body onload=alert(1)>",
    "<iframe src='javascript:alert(1)'></iframe>",
    '<a href="javascript:alert(1)">click</a>',
    '<a href="JaVaScRiPt:alert(1)">click</a>',
    '<a href="  javascript:alert(1)">click</a>',
    '<a href="java\tscript:alert(1)">click</a>',
    '<a href="&#106;avascript:alert(1)">click</a>',
    '<a href="data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==">x</a>',
    "<style>body{background:url('javascript:alert(1)')}</style>",
    '<div onmouseover="alert(1)">hover</div>',
    "<object data='javascript:alert(1)'></object>",
    "<embed src='javascript:alert(1)'>",
    "<math><mtext><script>alert(1)</script></mtext></math>",
    "<!--[if IE]><script>alert(1)</script><![endif]-->",
    "<form action='javascript:alert(1)'><input formaction='javascript:alert(1)'></form>",
    '<img src="x" onerror="alert(\'1\')" />',
]


@pytest.mark.parametrize("vector", XSS_VECTORS)
def test_known_xss_vectors_leave_no_executable_residue(vector: str) -> None:
    cleaned = sanitize_rich_text(vector).html
    lowered = cleaned.lower()
    assert "<script" not in lowered
    assert "javascript:" not in lowered
    assert "onerror" not in lowered
    assert "onload" not in lowered
    assert "onmouseover" not in lowered
    assert "<iframe" not in lowered
    assert "<svg" not in lowered
    assert "<style" not in lowered
    assert "data:text/html" not in lowered


def test_script_content_is_dropped_not_merely_unwrapped() -> None:
    """Unwrapping a script would paste its source into the page as text."""

    cleaned = sanitize_rich_text("<p>before</p><script>alert('boom')</script><p>after</p>")
    assert "alert" not in cleaned.html
    assert cleaned.html == "<p>before</p><p>after</p>"
    assert "script" in cleaned.removed_tags


def test_event_handler_attributes_are_removed_by_name_prefix() -> None:
    cleaned = sanitize_rich_text('<p onclick="x" onfuturething="y">text</p>')
    assert cleaned.html == "<p>text</p>"
    assert "p@onclick" in cleaned.removed_attributes
    assert "p@onfuturething" in cleaned.removed_attributes


def test_allowed_markup_survives_intact() -> None:
    source = '<p>Hello <strong>world</strong> and <a href="/about" title="t">link</a></p>'
    cleaned = sanitize_rich_text(source)
    assert cleaned.html == source
    assert cleaned.was_modified is False


def test_a_disallowed_tag_is_unwrapped_and_its_text_is_kept() -> None:
    cleaned = sanitize_rich_text("<div>kept text</div>")
    assert cleaned.html == "kept text"
    assert "div" in cleaned.removed_tags


def test_text_is_escaped_so_it_cannot_become_markup() -> None:
    cleaned = sanitize_rich_text("<p>5 &lt; 6 &amp; 7 > 2</p>")
    assert "&lt;" in cleaned.html
    assert "&amp;" in cleaned.html


def test_relative_and_https_links_are_allowed() -> None:
    for href in ("/about", "https://example.com/x", "mailto:a@example.com", "#anchor"):
        cleaned = sanitize_rich_text(f'<a href="{href}">x</a>')
        assert f'href="{href}"' in cleaned.html


def test_protocol_relative_links_are_rejected() -> None:
    cleaned = sanitize_rich_text('<a href="//evil.example/x">x</a>')
    assert "href=" not in cleaned.html


def test_only_the_named_url_schemes_are_permitted() -> None:
    assert "javascript" not in ALLOWED_URL_SCHEMES
    assert "data" not in ALLOWED_URL_SCHEMES
    assert frozenset({"http", "https", "mailto", "tel"}) == ALLOWED_URL_SCHEMES


def test_unbalanced_input_produces_balanced_output() -> None:
    cleaned = sanitize_rich_text("<p><strong>bold")
    assert cleaned.html == "<p><strong>bold</strong></p>"


def test_a_blank_target_gets_noopener() -> None:
    cleaned = sanitize_rich_text('<a href="https://example.com" target="_blank">x</a>')
    assert 'rel="noopener noreferrer"' in cleaned.html


def test_over_long_rich_text_is_refused() -> None:
    with pytest.raises(CmsRuleError) as excinfo:
        sanitize_rich_text("<p>x</p>" * 1000, max_length=100)
    assert excinfo.value.code == "CMS_BODY_TOO_LONG"


def test_the_allow_list_contains_no_scripting_capable_tags() -> None:
    for tag in ("script", "style", "iframe", "object", "embed", "svg", "form"):
        assert tag not in ALLOWED_TAGS


def test_plain_text_extraction_flattens_markup() -> None:
    assert extract_plain_text("<p>one</p><p>two</p>") == "one two"


# ---------------------------------------------------------------------------
# Translation fallback
# ---------------------------------------------------------------------------


def test_the_requested_locale_is_served_without_a_fallback_marker() -> None:
    resolved = resolve_localization([_body("zh-CN"), _body("en-US")], requested_locale="en-US")
    assert resolved.served_locale == "en-US"
    assert resolved.translation_fallback is False
    assert resolved.fallback_reason is None


def test_a_missing_translation_falls_back_and_says_so() -> None:
    """The documented fallback: default-locale content plus an explicit flag."""

    resolved = resolve_localization([_body("zh-CN")], requested_locale="en-US")
    assert resolved.served_locale == DEFAULT_LOCALE
    assert resolved.translation_fallback is True
    assert resolved.fallback_reason == "default_locale_fallback"
    payload = resolved.as_dict()
    assert payload["translation_fallback"] is True
    assert payload["requested_locale"] == "en-US"
    assert payload["served_locale"] == "zh-CN"


def test_a_region_variant_is_preferred_over_the_default_locale() -> None:
    resolved = resolve_localization([_body("zh-CN"), _body("en-US")], requested_locale="en-GB")
    assert resolved.served_locale == "en-US"
    assert resolved.translation_fallback is True
    assert resolved.fallback_reason == "locale_region_fallback"


def test_an_unpublished_translation_counts_as_missing_for_a_member() -> None:
    bodies = [_body("zh-CN"), _body("en-US", status=LocaleStatus.DRAFT)]
    resolved = resolve_localization(bodies, requested_locale="en-US")
    assert resolved.served_locale == "zh-CN"
    assert resolved.translation_fallback is True
    assert "en-US" not in resolved.available_locales


def test_a_draft_translation_is_visible_in_preview_mode() -> None:
    bodies = [_body("zh-CN"), _body("en-US", status=LocaleStatus.DRAFT)]
    resolved = resolve_localization(bodies, requested_locale="en-US", published_only=False)
    assert resolved.served_locale == "en-US"
    assert resolved.translation_fallback is False


def test_no_visible_locale_at_all_raises_rather_than_returning_a_blank_page() -> None:
    with pytest.raises(CmsRuleError) as excinfo:
        resolve_localization(
            [_body("fr-FR")], requested_locale="en-US", default_locale=DEFAULT_LOCALE
        )
    assert excinfo.value.code == "CMS_TRANSLATION_MISSING"


def test_the_available_locales_are_reported_for_a_language_switcher() -> None:
    resolved = resolve_localization([_body("zh-CN"), _body("en-US")], requested_locale="zh-CN")
    assert resolved.available_locales == ("en-US", "zh-CN")
    assert set(SUPPORTED_LOCALES) == {"zh-CN", "en-US"}


# ---------------------------------------------------------------------------
# Publishing workflow
# ---------------------------------------------------------------------------


def test_the_publish_workflow_allows_only_the_documented_transitions() -> None:
    validate_entry_transition(EntryStatus.DRAFT.value, EntryStatus.IN_REVIEW.value)
    validate_entry_transition(EntryStatus.IN_REVIEW.value, EntryStatus.PUBLISHED.value)
    validate_entry_transition(EntryStatus.PUBLISHED.value, EntryStatus.ARCHIVED.value)
    with pytest.raises(CmsRuleError) as excinfo:
        validate_entry_transition(EntryStatus.DRAFT.value, EntryStatus.PUBLISHED.value)
    assert excinfo.value.code == "CMS_TRANSITION_INVALID"


def test_an_unknown_status_is_refused() -> None:
    with pytest.raises(CmsRuleError) as excinfo:
        validate_entry_transition("nonsense", EntryStatus.DRAFT.value)
    assert excinfo.value.code == "CMS_STATUS_UNKNOWN"


def test_a_scheduled_entry_is_not_visible_before_its_time() -> None:
    assert (
        is_entry_member_visible(
            EntryStatus.PUBLISHED.value, published_at=NOW + timedelta(hours=1), now=NOW
        )
        is False
    )
    assert (
        is_entry_member_visible(
            EntryStatus.PUBLISHED.value, published_at=NOW - timedelta(hours=1), now=NOW
        )
        is True
    )
    assert is_entry_member_visible(EntryStatus.DRAFT.value, published_at=NOW, now=NOW) is False


def test_publishing_without_the_default_locale_is_refused() -> None:
    """Otherwise the fallback rule would have nothing to fall back to."""

    with pytest.raises(CmsRuleError) as excinfo:
        ensure_publishable(bodies=[_body("en-US")], now=NOW)
    assert excinfo.value.code == "CMS_DEFAULT_LOCALE_MISSING"


def test_publishing_with_an_empty_default_body_is_refused() -> None:
    empty = LocalizedBody(locale=DEFAULT_LOCALE, title="t", body_html="<p></p>")
    with pytest.raises(CmsRuleError) as excinfo:
        ensure_publishable(bodies=[empty], now=NOW)
    assert excinfo.value.code == "CMS_DEFAULT_LOCALE_EMPTY"


def test_a_schedule_in_the_past_is_refused() -> None:
    with pytest.raises(CmsRuleError) as excinfo:
        ensure_publishable(
            bodies=[_body(DEFAULT_LOCALE)], scheduled_for=NOW - timedelta(minutes=1), now=NOW
        )
    assert excinfo.value.code == "CMS_SCHEDULE_IN_PAST"


def test_a_complete_entry_is_publishable() -> None:
    ensure_publishable(bodies=[_body(DEFAULT_LOCALE), _body("en-US")], seo=_seo(), now=NOW)


# ---------------------------------------------------------------------------
# SEO metadata
# ---------------------------------------------------------------------------


def test_seo_metadata_bounds_are_enforced() -> None:
    with pytest.raises(CmsRuleError) as excinfo:
        validate_seo_metadata(_seo(seo_title="x" * 80))
    assert excinfo.value.code == "CMS_SEO_TITLE_TOO_LONG"
    with pytest.raises(CmsRuleError):
        validate_seo_metadata(_seo(seo_description="x" * 200))


def test_a_canonical_url_must_stay_on_this_site() -> None:
    with pytest.raises(CmsRuleError) as excinfo:
        validate_seo_metadata(_seo(canonical_path="https://evil.example/x"))
    assert excinfo.value.code == "CMS_CANONICAL_NOT_RELATIVE"


def test_contradictory_robots_directives_are_refused() -> None:
    with pytest.raises(CmsRuleError) as excinfo:
        validate_seo_metadata(_seo(robots=("index", "noindex")))
    assert excinfo.value.code == "CMS_ROBOTS_DIRECTIVE_CONFLICT"


def test_an_unknown_robots_directive_is_refused() -> None:
    with pytest.raises(CmsRuleError) as excinfo:
        validate_seo_metadata(_seo(robots=("indexx",)))
    assert excinfo.value.code == "CMS_ROBOTS_DIRECTIVE_UNKNOWN"


def test_seo_defaults_are_derived_from_the_content() -> None:
    body = LocalizedBody(
        locale=DEFAULT_LOCALE, title="A title", body_html="<p>Some body text</p>", summary=""
    )
    seo = derive_seo_defaults(body, canonical_path="/a")
    assert seo.seo_title == "A title"
    assert seo.seo_description == "Some body text"
    validate_seo_metadata(seo)


def test_a_long_summary_is_truncated_at_a_word_boundary() -> None:
    body = LocalizedBody(
        locale=DEFAULT_LOCALE,
        title="t",
        body_html="<p>x</p>",
        summary=" ".join(["word"] * 100),
    )
    seo = derive_seo_defaults(body, canonical_path="/a")
    assert len(seo.seo_description) <= 160
    assert not seo.seo_description.endswith("wor")


# ---------------------------------------------------------------------------
# Revisions and rollback
# ---------------------------------------------------------------------------


def _revision(number: int, *, action: RevisionAction = RevisionAction.EDITED) -> Revision:
    return Revision(
        revision_number=number,
        content_hash=f"hash-{number}",
        action=action,
        created_at=NOW - timedelta(days=10 - number),
    )


def test_revision_numbers_increase_monotonically() -> None:
    assert next_revision_number([]) == 1
    assert next_revision_number([_revision(1), _revision(3), _revision(2)]) == 4


def test_a_rollback_creates_a_new_revision_rather_than_rewriting_history() -> None:
    revisions = [_revision(1), _revision(2), _revision(3)]
    plan = plan_rollback(revisions, target_revision_number=1, now=NOW)
    assert plan.new_revision_number == 4
    assert plan.source_revision_number == 1
    assert plan.content_hash == "hash-1"


def test_rolling_back_to_the_current_head_is_a_no_op_and_is_refused() -> None:
    with pytest.raises(CmsRuleError) as excinfo:
        plan_rollback([_revision(1), _revision(2)], target_revision_number=2, now=NOW)
    assert excinfo.value.code == "CMS_ROLLBACK_NO_OP"


def test_rolling_back_to_an_unknown_revision_is_refused() -> None:
    with pytest.raises(CmsRuleError) as excinfo:
        plan_rollback([_revision(1)], target_revision_number=9, now=NOW)
    assert excinfo.value.code == "CMS_REVISION_NOT_FOUND"


def test_a_fingerprint_changes_when_any_locale_changes() -> None:
    base = [_body("zh-CN"), _body("en-US")]
    changed = [_body("zh-CN"), LocalizedBody("en-US", "Other", "<p>Other</p>")]
    assert content_fingerprint(base) != content_fingerprint(changed)
    assert content_fingerprint(base) == content_fingerprint(list(reversed(base)))


def test_a_fingerprint_changes_when_seo_changes() -> None:
    bodies = [_body(DEFAULT_LOCALE)]
    assert content_fingerprint(bodies, _seo()) != content_fingerprint(
        bodies, _seo(seo_title="Different")
    )


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def test_a_preview_claim_is_pinned_to_a_revision() -> None:
    claim = build_preview_claim(
        entry_id="entry-1", revision_number=3, issued_at=NOW, ttl_minutes=60
    )
    assert claim.revision_number == 3
    assert claim.expires_at == NOW + timedelta(minutes=60)
    assert claim.as_payload()["revision_number"] == 3


def test_an_expired_preview_is_refused() -> None:
    claim = build_preview_claim(entry_id="entry-1", revision_number=1, issued_at=NOW, ttl_minutes=1)
    with pytest.raises(CmsRuleError) as excinfo:
        ensure_preview_valid(claim, now=NOW + timedelta(minutes=2), revoked_at=None)
    assert excinfo.value.code == "CMS_PREVIEW_EXPIRED"


def test_a_revoked_preview_is_refused_before_it_expires() -> None:
    claim = build_preview_claim(
        entry_id="entry-1", revision_number=1, issued_at=NOW, ttl_minutes=60
    )
    with pytest.raises(CmsRuleError) as excinfo:
        ensure_preview_valid(
            claim, now=NOW + timedelta(minutes=1), revoked_at=NOW + timedelta(seconds=30)
        )
    assert excinfo.value.code == "CMS_PREVIEW_REVOKED"


def test_a_live_preview_passes() -> None:
    claim = build_preview_claim(
        entry_id="entry-1", revision_number=1, issued_at=NOW, ttl_minutes=60
    )
    ensure_preview_valid(claim, now=NOW + timedelta(minutes=1), revoked_at=None)


def test_naive_timestamps_are_refused() -> None:
    with pytest.raises(CmsRuleError) as excinfo:
        build_preview_claim(
            entry_id="e", revision_number=1, issued_at=datetime(2026, 8, 12), ttl_minutes=10
        )
    assert excinfo.value.code == "CMS_NAIVE_DATETIME"
