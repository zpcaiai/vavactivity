# ruff: noqa: E501

"""Give content localizations a home for canonical path and robots directives.

Migration 0108 folded the CMS console onto ``content_localizations``, which
already carried ``seo_title`` / ``seo_description`` / the social pair. Two SEO
fields had nowhere to go:

* ``canonical_path`` — an editor-set canonical, needed whenever the same story
  is reachable at more than one URL.
* ``robots`` — the directive list, which is how an editor marks a page
  ``noindex``.

Without them the live page silently fell back to a derived canonical and an
implicit ``index, follow``. An editor could set "do not index" in the console
and the page would be indexed anyway — a quiet wrong answer, which is exactly
what CMS-001 asks the publishing surface not to produce.

Revision ID: 20260812_0109
Revises: 20260812_0108
"""

import re

from alembic import op

revision = "20260812_0109"
down_revision = "20260812_0108"
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
        ALTER TABLE content_localizations
          ADD COLUMN IF NOT EXISTS canonical_path VARCHAR(500),
          ADD COLUMN IF NOT EXISTS robots JSONB NOT NULL DEFAULT '["index","follow"]'::jsonb;

        -- A canonical must stay internal: an absolute URL here would let an
        -- editor point the site's own canonical at somewhere else entirely.
        ALTER TABLE content_localizations
          ADD CONSTRAINT content_localizations_canonical_path_internal
          CHECK (canonical_path IS NULL OR canonical_path ~ '^/');

        ALTER TABLE content_localizations
          ADD CONSTRAINT content_localizations_robots_is_array
          CHECK (jsonb_typeof(robots) = 'array');
        """
    )


def downgrade() -> None:
    _run(
        """
        ALTER TABLE content_localizations
          DROP CONSTRAINT IF EXISTS content_localizations_robots_is_array;
        ALTER TABLE content_localizations
          DROP CONSTRAINT IF EXISTS content_localizations_canonical_path_internal;
        ALTER TABLE content_localizations
          DROP COLUMN IF EXISTS robots,
          DROP COLUMN IF EXISTS canonical_path;
        """
    )
