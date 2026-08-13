# ruff: noqa: E501

"""Merge the ``cms_*`` publishing namespace into the existing content tables.

Batch B19 created ``cms_entries``, ``cms_entry_locales``,
``cms_entry_revisions``, ``cms_seo_metadata``, ``cms_preview_grants`` and
``cms_publish_events`` beside the pre-existing ``content_entries`` /
``content_localizations`` / ``content_versions`` / ``content_preview_tokens``.
Two namespaces for the same thing is a correctness defect, not a style problem:

* the public site, the sitemap and the navigation resolver all read
  ``content_entries`` / ``content_localizations``;
* nothing reads ``cms_entries``.

So an editor who published through the new console produced a row nobody
serves - the page stayed invisible while the console said "published". This
migration keeps the established tables and folds the newer ones into them.

How the columns map:

* ``cms_entries``            -> ``content_entries`` (``entry_code`` becomes
  ``canonical_slug``, ``content_type`` becomes ``entry_type``,
  ``published_revision_number`` becomes ``current_version``).
* ``cms_entry_locales``      -> ``content_localizations``. The body becomes a
  ``rich_text`` block in ``content_blocks`` - the column the site renders -
  carrying the already-sanitized HTML, with ``body_plain`` in ``plain_text``.
* ``cms_seo_metadata``       -> the SEO columns of ``content_localizations``.
  ``canonical_path`` and ``robots`` have no column there; they survive inside
  the version snapshot below and are not invented as new columns here.
* ``cms_entry_revisions``    -> ``content_versions``, with the locale payload,
  the SEO payload and the sanitizer report merged into the one ``snapshot``.
* ``cms_preview_grants``     -> ``content_preview_tokens``. A link issued
  before this migration will no longer resolve: the revision it pinned was
  recoverable only from the grant row, and ``content_preview_tokens`` has no
  revision column. The rows are still carried across so a revocation stays on
  record; the links themselves expire within their TTL (24 hours at most).
* ``cms_publish_events``     -> ``audit_events``, the platform's append-only
  log. No replacement table is created.

Two rows this migration deliberately cannot carry:

* ``content_entries.author_id`` is NOT NULL while ``cms_entries.created_by``
  was nullable, so an entry with no author at all is left behind rather than
  attributed to somebody who did not write it.
* ``localized_slug`` is left NULL. It is unique per ``(locale, localized_slug)``
  across every entry type, so filling it from the entry code would make two
  entries that legitimately share a code collide.

Revision ID: 20260812_0108
Revises: 20260812_0107
"""

import re

from alembic import op

revision = "20260812_0108"
down_revision = "20260812_0107"
branch_labels = None
depends_on = None


def _split_statements(script: str) -> list[str]:
    """Split a SQL script on statement boundaries.

    A naive ``script.split(";")`` breaks on any semicolon, including ones
    inside a ``--`` comment or a string literal — which silently turns the
    remainder of a comment into a bogus statement. Postgres then fails on
    something like ``syntax error at or near "it"``, pointing at a line that
    looks perfectly fine.

    This walks the script instead, skipping over line comments, block
    comments, single-quoted strings and dollar-quoted bodies.
    """

    statements: list[str] = []
    buffer: list[str] = []
    index = 0
    length = len(script)
    while index < length:
        char = script[index]
        pair = script[index : index + 2]
        if pair == "--":
            end = script.find("\n", index)
            index = length if end == -1 else end
            continue
        if pair == "/*":
            end = script.find("*/", index + 2)
            index = length if end == -1 else end + 2
            continue
        if char == "'":
            buffer.append(char)
            index += 1
            while index < length:
                buffer.append(script[index])
                if script[index] == "'":
                    if script[index : index + 2] == "''":
                        buffer.append(script[index + 1])
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        if char == "$":
            match = re.match(r"\$[A-Za-z_]*\$", script[index:])
            if match:
                tag = match.group(0)
                end = script.find(tag, index + len(tag))
                stop = length if end == -1 else end + len(tag)
                buffer.append(script[index:stop])
                index = stop
                continue
        if char == ";":
            statements.append("".join(buffer))
            buffer = []
            index += 1
            continue
        buffer.append(char)
        index += 1
    statements.append("".join(buffer))
    return [item.strip() for item in statements if item.strip()]


def _run(script: str) -> None:
    for statement in _split_statements(script):
        op.execute(statement)


def upgrade() -> None:
    # Entries first: everything below is keyed on an entry surviving the move,
    # so a row skipped here takes its locales, revisions and previews with it.
    op.execute(
        """
        INSERT INTO content_entries
          (id, entry_type, internal_name, canonical_slug, status, default_locale, visibility,
           author_id, published_by, scheduled_publish_at, published_at, archived_at,
           current_version, version, created_at, updated_at)
        SELECT
          c.id,
          left(c.content_type, 32),
          left(COALESCE(NULLIF(btrim(l.title), ''), c.entry_code), 160),
          left(c.entry_code, 200),
          c.status,
          c.default_locale,
          'public',
          COALESCE(c.created_by, c.updated_by),
          CASE WHEN c.status = 'published' THEN COALESCE(c.updated_by, c.created_by) END,
          c.scheduled_publish_at,
          c.published_at,
          c.archived_at,
          COALESCE(c.published_revision_number, 1),
          c.version,
          c.created_at,
          c.updated_at
        FROM cms_entries c
        LEFT JOIN cms_entry_locales l ON l.entry_id = c.id AND l.locale = c.default_locale
        WHERE COALESCE(c.created_by, c.updated_by) IS NOT NULL
        ON CONFLICT DO NOTHING;
        """
    )

    # The body moves into content_blocks as a rich_text block: that is the
    # column the site renders, and the HTML in it already went through the
    # allow-list sanitizer on write.
    op.execute(
        """
        INSERT INTO content_localizations
          (entry_id, locale, title, excerpt, content_blocks, plain_text,
           seo_title, seo_description, social_title, social_description,
           cover_media_id, translation_status, created_at, updated_at)
        SELECT
          l.entry_id,
          l.locale,
          left(l.title, 300),
          NULLIF(l.summary, ''),
          jsonb_build_array(
            jsonb_build_object(
              'id', 'body',
              'type', 'rich_text',
              'version', 1,
              'data', jsonb_build_object(
                'document', jsonb_build_object('format', 'sanitized_html', 'html', l.body_html)
              )
            )
          ),
          NULLIF(l.body_plain, ''),
          left(s.seo_title, 300),
          left(s.seo_description, 500),
          left(s.seo_title, 300),
          left(s.seo_description, 500),
          s.og_image_media_id,
          l.status,
          l.created_at,
          l.updated_at
        FROM cms_entry_locales l
        LEFT JOIN cms_seo_metadata s ON s.entry_id = l.entry_id AND s.locale = l.locale
        WHERE EXISTS (SELECT 1 FROM content_entries e WHERE e.id = l.entry_id)
        ON CONFLICT DO NOTHING;
        """
    )

    # Locale payload, SEO payload and sanitizer report merge into the single
    # snapshot column, so a rollback still restores the canonical path and the
    # robots directives that content_localizations cannot hold.
    op.execute(
        """
        INSERT INTO content_versions
          (entry_id, version_number, snapshot, change_summary, created_by, created_at)
        SELECT
          r.entry_id,
          r.revision_number,
          jsonb_build_object(
            'revision_number', r.revision_number,
            'action', r.action,
            'content_hash', r.content_hash,
            'source_revision_number', r.source_revision_number,
            'sanitizer_report', r.sanitizer_report,
            'locales', r.locale_payload,
            'seo', r.seo_payload
          ),
          'Migrated from cms_entry_revisions (' || r.action || ').',
          COALESCE(r.author_id, e.author_id),
          r.created_at
        FROM cms_entry_revisions r
        JOIN content_entries e ON e.id = r.entry_id
        ON CONFLICT DO NOTHING;
        """
    )

    op.execute(
        """
        INSERT INTO content_preview_tokens
          (id, entry_id, token_hash, locale, created_by, expires_at, revoked_at, created_at)
        SELECT
          g.id,
          g.entry_id,
          g.token_hash,
          NULL,
          COALESCE(g.issued_by, e.author_id),
          g.expires_at,
          g.revoked_at,
          g.issued_at
        FROM cms_preview_grants g
        JOIN content_entries e ON e.id = g.entry_id
        ON CONFLICT DO NOTHING;
        """
    )

    # The publishing trail keeps its own history rather than a replacement
    # table: audit_events is append-only (a trigger rejects UPDATE and DELETE)
    # and is where operators already look.
    op.execute(
        """
        INSERT INTO audit_events
          (actor_id, actor_type, action, subject_type, subject_id, reason, context, occurred_at)
        SELECT
          p.actor_id::text,
          'administrator',
          left('cms.entry.' || p.action, 120),
          'content_entry',
          p.entry_id::text,
          p.reason,
          jsonb_build_object(
            'revision_number', p.revision_number,
            'migrated_from', 'cms_publish_events'
          ),
          p.occurred_at
        FROM cms_publish_events p
        WHERE EXISTS (SELECT 1 FROM content_entries e WHERE e.id = p.entry_id);
        """
    )

    _run(
        """
        DROP TABLE IF EXISTS cms_publish_events;
        DROP TABLE IF EXISTS cms_preview_grants;
        DROP TABLE IF EXISTS cms_seo_metadata;
        DROP TABLE IF EXISTS cms_entry_revisions;
        DROP TABLE IF EXISTS cms_entry_locales;
        DROP TABLE IF EXISTS cms_entries;
        """
    )


def downgrade() -> None:
    # The merged rows are deliberately NOT unmerged: they are now part of the
    # tables the site serves and may have been edited, published or rolled back
    # there since. Recreating the tables empty restores the schema shape
    # without inventing history.
    _run(
        """
        CREATE TABLE IF NOT EXISTS cms_entries (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entry_code VARCHAR(128) NOT NULL,
          content_type VARCHAR(64) NOT NULL,
          status VARCHAR(16) NOT NULL DEFAULT 'draft',
          default_locale VARCHAR(16) NOT NULL DEFAULT 'zh-CN',
          scheduled_publish_at TIMESTAMPTZ,
          published_at TIMESTAMPTZ,
          published_revision_number INTEGER,
          created_by UUID REFERENCES users(id),
          updated_by UUID REFERENCES users(id),
          version INTEGER NOT NULL DEFAULT 1,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          archived_at TIMESTAMPTZ,
          UNIQUE (entry_code),
          CHECK (status IN ('draft','in_review','scheduled','published','archived')),
          CHECK (status <> 'published' OR (published_at IS NOT NULL AND published_revision_number IS NOT NULL)),
          CHECK (status <> 'scheduled' OR scheduled_publish_at IS NOT NULL)
        );
        CREATE INDEX IF NOT EXISTS cms_entries_public_idx
          ON cms_entries (content_type, published_at DESC) WHERE status = 'published';

        CREATE TABLE IF NOT EXISTS cms_entry_locales (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entry_id UUID NOT NULL REFERENCES cms_entries(id) ON DELETE CASCADE,
          locale VARCHAR(16) NOT NULL,
          title VARCHAR(300) NOT NULL,
          summary TEXT NOT NULL DEFAULT '',
          body_html TEXT NOT NULL,
          body_plain TEXT NOT NULL DEFAULT '',
          status VARCHAR(16) NOT NULL DEFAULT 'draft',
          translation_source_locale VARCHAR(16),
          updated_by UUID REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (entry_id, locale),
          CHECK (status IN ('draft','ready','published')),
          CHECK (length(btrim(title)) > 0)
        );
        CREATE INDEX IF NOT EXISTS cms_entry_locales_published_idx
          ON cms_entry_locales (entry_id, locale) WHERE status = 'published';

        CREATE TABLE IF NOT EXISTS cms_entry_revisions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entry_id UUID NOT NULL REFERENCES cms_entries(id) ON DELETE CASCADE,
          revision_number INTEGER NOT NULL,
          locale_payload JSONB NOT NULL DEFAULT '[]'::jsonb,
          seo_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
          sanitizer_report JSONB NOT NULL DEFAULT '{}'::jsonb,
          content_hash VARCHAR(64) NOT NULL,
          action VARCHAR(16) NOT NULL,
          source_revision_number INTEGER,
          author_id UUID REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (entry_id, revision_number),
          CHECK (revision_number >= 1),
          CHECK (action IN ('created','edited','published','rolled_back')),
          CHECK (action <> 'rolled_back' OR source_revision_number IS NOT NULL),
          CHECK (source_revision_number IS NULL OR source_revision_number < revision_number),
          CHECK (jsonb_typeof(locale_payload) = 'array')
        );

        CREATE TABLE IF NOT EXISTS cms_seo_metadata (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entry_id UUID NOT NULL REFERENCES cms_entries(id) ON DELETE CASCADE,
          locale VARCHAR(16) NOT NULL,
          seo_title VARCHAR(70) NOT NULL,
          seo_description VARCHAR(160) NOT NULL DEFAULT '',
          canonical_path VARCHAR(500) NOT NULL,
          robots JSONB NOT NULL DEFAULT '["index","follow"]'::jsonb,
          og_image_media_id UUID,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (entry_id, locale),
          CHECK (canonical_path LIKE '/%' AND canonical_path NOT LIKE '//%'),
          CHECK (jsonb_typeof(robots) = 'array')
        );

        CREATE TABLE IF NOT EXISTS cms_preview_grants (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entry_id UUID NOT NULL REFERENCES cms_entries(id) ON DELETE CASCADE,
          revision_number INTEGER NOT NULL,
          token_hash VARCHAR(64) NOT NULL,
          audience VARCHAR(24) NOT NULL DEFAULT 'internal',
          issued_by UUID REFERENCES users(id),
          issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          expires_at TIMESTAMPTZ NOT NULL,
          revoked_at TIMESTAMPTZ,
          revoked_by UUID REFERENCES users(id),
          UNIQUE (token_hash),
          CHECK (audience IN ('internal','external_reviewer')),
          CHECK (expires_at > issued_at),
          CHECK (revision_number >= 1)
        );
        CREATE INDEX IF NOT EXISTS cms_preview_grants_entry_idx
          ON cms_preview_grants (entry_id, expires_at DESC);

        CREATE TABLE IF NOT EXISTS cms_publish_events (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entry_id UUID NOT NULL REFERENCES cms_entries(id) ON DELETE CASCADE,
          revision_number INTEGER,
          action VARCHAR(24) NOT NULL,
          actor_id UUID REFERENCES users(id),
          reason TEXT,
          occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS cms_publish_events_entry_idx
          ON cms_publish_events (entry_id, occurred_at DESC);
        """
    )
