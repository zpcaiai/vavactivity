# ruff: noqa: E501

"""Split content_entries.current_version into head-of-history and live-revision.

``current_version`` was carrying two incompatible meanings at once:

* the older content console treated it as its own edit counter — bump it, then
  write a ``content_versions`` row numbered with it;
* ``cms_publishing`` treated it as "the revision members are reading" and set
  it to the head of history on publish.

The two only agree while a single console touches an entry. As soon as the CMS
console appends revisions (which it does without touching ``current_version``),
the counter falls behind the real head, and the next edit in the old console
tries to write a ``content_versions`` row whose number is already taken. That
is a unique-constraint violation on
``content_versions_entry_id_version_number_key`` — a 500 on save, reproducible
in three writes — not a cosmetic disagreement.

This migration gives each meaning its own home:

* ``current_version`` keeps one meaning only — the head revision number — and
  is repaired here to the true maximum so the next append cannot collide.
* ``published_revision_number`` is new and holds the revision that is live.
  ``NULL`` means never published, which is a state the old overloading could
  not express at all.

The backfill is deliberately conservative. For an entry that is currently
published, the live revision is taken to be the value ``current_version``
already held, because that is exactly what the publish path wrote there. For
anything else it stays NULL rather than guessing.

Revision ID: 20260813_0110
Revises: 20260812_0109
"""

import re

from alembic import op

revision = "20260813_0110"
down_revision = "20260812_0109"
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
        ALTER TABLE content_entries
          ADD COLUMN IF NOT EXISTS published_revision_number INTEGER;

        -- Order matters: capture what current_version meant for published
        -- entries BEFORE repairing current_version to the true head, or the
        -- repair overwrites the only record of which revision went live.
        UPDATE content_entries
           SET published_revision_number = current_version
         WHERE status = 'published'
           AND published_revision_number IS NULL
           AND current_version > 0;

        -- Repair the counter to the real head of history. GREATEST keeps
        -- entries whose counter is already ahead of their snapshots (possible
        -- for an entry edited before snapshots existed) from moving backwards
        -- onto a number that history may later claim.
        UPDATE content_entries e
           SET current_version = GREATEST(
                 e.current_version,
                 COALESCE((SELECT max(v.version_number)
                             FROM content_versions v
                            WHERE v.entry_id = e.id), 0),
                 1
               );

        -- Safety net for any published row the first pass could not derive a
        -- pin for (a zero or absent counter). It runs after the repair, so
        -- current_version is guaranteed to be a real revision number by now.
        UPDATE content_entries
           SET published_revision_number = current_version
         WHERE status = 'published'
           AND published_revision_number IS NULL;

        ALTER TABLE content_entries
          ADD CONSTRAINT content_entries_published_revision_positive
          CHECK (published_revision_number IS NULL OR published_revision_number > 0);

        -- A published entry must name the revision it is serving. Without this
        -- the "which revision is live" question silently falls back to the
        -- head again, which is the bug this migration exists to end.
        --
        -- Added NOT VALID and validated immediately afterwards rather than in
        -- one step: the two-step form takes a weaker lock for the scan, and
        -- the explicit VALIDATE means the constraint is genuinely enforced for
        -- existing rows rather than only for future writes. A constraint left
        -- permanently NOT VALID would read as a guarantee it does not give.
        ALTER TABLE content_entries
          ADD CONSTRAINT content_entries_published_revision_present
          CHECK (status <> 'published' OR published_revision_number IS NOT NULL)
          NOT VALID;

        ALTER TABLE content_entries
          VALIDATE CONSTRAINT content_entries_published_revision_present;
        """
    )


def downgrade() -> None:
    # current_version is deliberately left at the repaired value. Moving it
    # back to a stale counter would re-arm the collision this migration fixed,
    # and the pre-repair value is not recoverable anyway.
    _run(
        """
        ALTER TABLE content_entries
          DROP CONSTRAINT IF EXISTS content_entries_published_revision_present;
        ALTER TABLE content_entries
          DROP CONSTRAINT IF EXISTS content_entries_published_revision_positive;
        ALTER TABLE content_entries
          DROP COLUMN IF EXISTS published_revision_number;
        """
    )
