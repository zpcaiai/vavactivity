# ruff: noqa: E501

"""Onsite check-in operations: last-four narrowing column, lookups, operation log, window policy.

Covers CHK-002.

Revision ID: 20260812_0105
Revises: 20260812_0104
"""

import re

from alembic import op

revision = "20260812_0105"
down_revision = "20260812_0104"
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
        -- The narrowing column. ``value_hmac`` is the HMAC of the *whole*
        -- number and by construction cannot be matched from a fragment, so a
        -- last-four search needs its own key. It is deliberately a separate,
        -- nullable column rather than a widened index on the existing one:
        --   * NULL means "this contact point predates the feature", which the
        --     lookup treats as "not findable by last four" - an honest miss
        --     rather than a partial match on the full-number HMAC.
        --   * The value is HMAC(deployment_salt, 'vN:1234'), never the four
        --     digits themselves, because 10^4 values are trivially enumerable
        --     from a table dump.
        -- This column narrows a candidate set. It is NOT an identity proof and
        -- nothing in the application resolves a person from it alone.
        ALTER TABLE user_contact_points ADD COLUMN IF NOT EXISTS last_four_hmac VARCHAR(128);
        CREATE INDEX IF NOT EXISTS user_contact_points_last_four_idx
          ON user_contact_points (last_four_hmac) WHERE last_four_hmac IS NOT NULL;

        CREATE TABLE checkin_lookup_sessions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          activity_id UUID NOT NULL REFERENCES activities(id),
          session_id UUID,
          operator_id UUID NOT NULL REFERENCES users(id),
          fragment_hmac VARCHAR(128) NOT NULL,
          outcome VARCHAR(24) NOT NULL,
          candidate_count INTEGER NOT NULL DEFAULT 0,
          issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          expires_at TIMESTAMPTZ NOT NULL,
          resolved_registration_id UUID REFERENCES activity_registrations(id),
          resolved_at TIMESTAMPTZ,
          discriminator_kind VARCHAR(32),
          device_reference VARCHAR(128),
          request_id VARCHAR(128),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (outcome IN ('no_match','single_candidate','ambiguous','too_many')),
          CHECK (expires_at > issued_at),
          -- A resolution without a recorded discriminator would mean somebody
          -- was identified by the fragment alone. The schema refuses it.
          CHECK (resolved_registration_id IS NULL OR discriminator_kind IS NOT NULL),
          CHECK (discriminator_kind IS NULL OR discriminator_kind IN ('name_initial','registration_suffix','both'))
        );
        CREATE INDEX checkin_lookup_sessions_operator_idx
          ON checkin_lookup_sessions (operator_id, issued_at DESC);
        CREATE INDEX checkin_lookup_sessions_activity_idx
          ON checkin_lookup_sessions (activity_id, issued_at DESC);

        CREATE TABLE checkin_lookup_candidates (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          lookup_id UUID NOT NULL REFERENCES checkin_lookup_sessions(id) ON DELETE CASCADE,
          registration_id UUID NOT NULL REFERENCES activity_registrations(id),
          position INTEGER NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (lookup_id, registration_id),
          CHECK (position >= 1)
        );

        -- The operator-behaviour trail. Separate from activity_checkin_events,
        -- whose ``action`` vocabulary is shared platform-wide and describes
        -- attendance transitions; the operations below include things that
        -- changed no attendance at all (a duplicate scan, a refusal).
        CREATE TABLE checkin_operation_events (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          activity_id UUID NOT NULL REFERENCES activities(id),
          session_id UUID,
          registration_id UUID REFERENCES activity_registrations(id),
          lookup_id UUID REFERENCES checkin_lookup_sessions(id),
          operator_id UUID NOT NULL REFERENCES users(id),
          operation VARCHAR(32) NOT NULL,
          outcome VARCHAR(32) NOT NULL,
          method VARCHAR(24) NOT NULL,
          device_reference VARCHAR(128),
          request_id VARCHAR(128),
          -- registration:device:request_id. Unique, so a scanner retrying a
          -- lost response lands on the existing row instead of double-writing.
          dedupe_key VARCHAR(255),
          reason TEXT,
          metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
          occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (dedupe_key),
          CHECK (operation IN ('lookup','select_candidate','confirm','undo','revoke','scan')),
          CHECK (operation <> 'undo' OR reason IS NOT NULL),
          CHECK (operation <> 'revoke' OR reason IS NOT NULL)
        );
        -- The rate limiter reads this index on every operator action, so it is
        -- ordered the way the limiter scans: newest first, per operator.
        CREATE INDEX checkin_operation_events_operator_idx
          ON checkin_operation_events (operator_id, activity_id, occurred_at DESC);
        CREATE INDEX checkin_operation_events_registration_idx
          ON checkin_operation_events (registration_id, occurred_at DESC);

        CREATE TABLE checkin_window_policies (
          activity_id UUID PRIMARY KEY REFERENCES activities(id),
          early_minutes INTEGER NOT NULL DEFAULT 60,
          late_minutes INTEGER NOT NULL DEFAULT 30,
          updated_by UUID REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (early_minutes >= 0 AND early_minutes <= 1440),
          CHECK (late_minutes >= 0 AND late_minutes <= 1440)
        );

        -- reason is NOT NULL. The permission answers "who may"; this column is
        -- the only thing that answers "why did they".
        CREATE TABLE checkin_window_overrides (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          activity_id UUID NOT NULL REFERENCES activities(id),
          session_id UUID,
          registration_id UUID NOT NULL REFERENCES activity_registrations(id),
          operator_id UUID NOT NULL REFERENCES users(id),
          window_state VARCHAR(24) NOT NULL,
          reason TEXT NOT NULL,
          occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (window_state IN ('too_early','too_late')),
          CHECK (length(btrim(reason)) >= 4)
        );
        CREATE INDEX checkin_window_overrides_activity_idx
          ON checkin_window_overrides (activity_id, occurred_at DESC);

        CREATE TABLE checkin_last_four_backfill_runs (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          requested_by UUID NOT NULL REFERENCES users(id),
          batch_size INTEGER NOT NULL DEFAULT 500,
          salt_version VARCHAR(16) NOT NULL DEFAULT 'v1',
          dry_run BOOLEAN NOT NULL DEFAULT true,
          pending_rows INTEGER NOT NULL DEFAULT 0,
          processed_rows INTEGER NOT NULL DEFAULT 0,
          status VARCHAR(16) NOT NULL DEFAULT 'queued',
          note TEXT,
          started_at TIMESTAMPTZ,
          finished_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (batch_size BETWEEN 1 AND 5000),
          CHECK (status IN ('queued','running','completed','failed','cancelled'))
        );
        """
    )

    # NO BACKFILL, ON PURPOSE.
    #
    # user_contact_points.value_encrypted is ciphertext and value_hmac is an
    # HMAC of the whole number. Neither can yield the last four digits inside
    # SQL: there is no plaintext in this database for a migration to read. The
    # only correct way to populate last_four_hmac is a job that runs with the
    # privacy decryption key, decrypts in batches and writes the derived HMAC -
    # which is exactly what checkin_last_four_backfill_runs books, and what the
    # ``privacy.contact_points.backfill`` permission gates.
    #
    # Until that job runs, contact points created before this migration have a
    # NULL last_four_hmac and simply do not appear in a last-four lookup. That
    # is the honest failure mode: an operator falls back to the QR credential or
    # to a name search. Faking it - matching a prefix of value_hmac, or storing
    # the four digits in plaintext "temporarily" - would either return wrong
    # people or reintroduce the very data this design keeps out.
    #
    # Operators: after deploying, set CHECKIN_LAST_FOUR_HMAC_KEY, then either
    # (a) run the backfill job, or (b) let the column populate naturally as
    # members re-verify their phone number. Option (b) is slower but needs no
    # bulk decryption; option (a) needs a maintenance window and an audit note.


def downgrade() -> None:
    _run(
        """
        DROP TABLE IF EXISTS checkin_last_four_backfill_runs;
        DROP TABLE IF EXISTS checkin_window_overrides;
        DROP TABLE IF EXISTS checkin_window_policies;
        DROP TABLE IF EXISTS checkin_operation_events;
        DROP TABLE IF EXISTS checkin_lookup_candidates;
        DROP TABLE IF EXISTS checkin_lookup_sessions;
        DROP INDEX IF EXISTS user_contact_points_last_four_idx;
        ALTER TABLE user_contact_points DROP COLUMN IF EXISTS last_four_hmac;
        """
    )
