# ruff: noqa: E501

"""Bilingual content entries, locales, revisions, SEO metadata and preview grants.

Covers CMS-001.

Two things this schema enforces that application code alone could not:

* ``cms_entry_revisions`` has no UPDATE path in the service and a UNIQUE
  ``(entry_id, revision_number)``: a rollback appends revision N+1 pointing at
  revision M, so "what did this page say last Tuesday" always has an answer.
* ``cms_entries`` carries a CHECK that a ``published`` row must have a
  ``published_at`` and a ``published_revision_number``. A page cannot be live
  without naming the exact revision that is live.

The existing ``content_entries`` / ``content_versions`` tables are **not**
touched or redefined. This module uses its own ``cms_`` namespace so it can be
deployed, rolled back and back-filled independently; a later migration can move
legacy rows across once the editorial workflow has settled.

Nothing is seeded. The platform ships no articles, no page copy and no SEO
text: ``cms_entries`` is empty after this migration and stays empty until an
editor writes something.

Revision ID: 20260812_0104
Revises: 20260812_0103
"""

import re

from alembic import op

revision = "20260812_0104"
down_revision = "20260812_0103"
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
    _run(
        """
        CREATE TABLE cms_entries (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entry_code VARCHAR(128) NOT NULL,
          content_type VARCHAR(64) NOT NULL,
          status VARCHAR(16) NOT NULL DEFAULT 'draft',
          -- The locale a missing translation falls back to. Stored per entry
          -- rather than assumed globally, so a source-English page can fall
          -- back to English.
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
        CREATE INDEX cms_entries_public_idx
          ON cms_entries (content_type, published_at DESC) WHERE status = 'published';

        -- One row per locale. body_html is already sanitized: the sanitizer
        -- runs on write, so no other consumer of this column can reproduce a
        -- payload the renderer would have stripped.
        CREATE TABLE cms_entry_locales (
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
        CREATE INDEX cms_entry_locales_published_idx
          ON cms_entry_locales (entry_id, locale) WHERE status = 'published';

        -- Append-only. The service never UPDATEs this table; a rollback writes
        -- a new row whose source_revision_number names what it restored.
        CREATE TABLE cms_entry_revisions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entry_id UUID NOT NULL REFERENCES cms_entries(id) ON DELETE CASCADE,
          revision_number INTEGER NOT NULL,
          locale_payload JSONB NOT NULL DEFAULT '[]'::jsonb,
          seo_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
          -- What the sanitizer removed when this revision was saved, so an
          -- editor asking "where did my embed go" gets an answer.
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

        CREATE TABLE cms_seo_metadata (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entry_id UUID NOT NULL REFERENCES cms_entries(id) ON DELETE CASCADE,
          locale VARCHAR(16) NOT NULL,
          seo_title VARCHAR(70) NOT NULL,
          seo_description VARCHAR(160) NOT NULL DEFAULT '',
          -- Site-relative only. An absolute canonical would hand ranking to
          -- whatever host the value names.
          canonical_path VARCHAR(500) NOT NULL,
          robots JSONB NOT NULL DEFAULT '["index","follow"]'::jsonb,
          og_image_media_id UUID,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (entry_id, locale),
          CHECK (canonical_path LIKE '/%' AND canonical_path NOT LIKE '//%'),
          CHECK (jsonb_typeof(robots) = 'array')
        );

        -- Only the hash of a preview token is stored, so reading this table
        -- cannot be turned into a working link to unpublished content.
        CREATE TABLE cms_preview_grants (
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
        CREATE INDEX cms_preview_grants_entry_idx ON cms_preview_grants (entry_id, expires_at DESC);

        -- Append-only publishing audit: who moved this page, when and why.
        CREATE TABLE cms_publish_events (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entry_id UUID NOT NULL REFERENCES cms_entries(id) ON DELETE CASCADE,
          revision_number INTEGER,
          action VARCHAR(24) NOT NULL,
          actor_id UUID REFERENCES users(id),
          reason TEXT,
          occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX cms_publish_events_entry_idx ON cms_publish_events (entry_id, occurred_at DESC);
        """
    )


def downgrade() -> None:
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
