# ruff: noqa: E501

"""Merge ai_hardening escalations into the existing ai_human_referrals queue.

Batch B19 introduced ``ai_human_escalations`` alongside the pre-existing
``ai_human_referrals``. Two queues for the same thing is a safety defect, not a
style problem:

* ``ai_assistant.tooling`` already files crisis referrals into
  ``ai_human_referrals``.
* ``privacy.service`` asks "does this member have an open referral?" against
  ``ai_human_referrals`` only.
* Whatever an operator watches, it is that table.

So an escalation written to the newer table would be invisible to the people
and the checks that are supposed to act on it. This migration keeps the
established queue and folds the two genuinely-new columns into it.

Revision ID: 20260812_0107
Revises: 20260812_0106
"""

import re

from alembic import op

revision = "20260812_0107"
down_revision = "20260812_0106"
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
        ALTER TABLE ai_human_referrals
          ADD COLUMN IF NOT EXISTS geography_code VARCHAR(8),
          ADD COLUMN IF NOT EXISTS runbook_id UUID REFERENCES ai_escalation_runbooks(id),
          ADD COLUMN IF NOT EXISTS severity INTEGER NOT NULL DEFAULT 0;

        CREATE INDEX IF NOT EXISTS ai_human_referrals_open_idx
          ON ai_human_referrals (status, created_at DESC)
          WHERE status NOT IN ('resolved', 'cancelled');
        """
    )

    # Carry any rows the newer table already collected across, mapping the
    # vocabulary onto the established one. `idempotency_key` is unique on the
    # target, so a re-run cannot duplicate an escalation.
    op.execute(
        """
        INSERT INTO ai_human_referrals
          (referral_number, conversation_id, user_id, referral_type, priority, risk_category,
           risk_level, status, assigned_team, consent_status, idempotency_key,
           geography_code, runbook_id, severity, created_at, acknowledged_at, resolved_at)
        SELECT
          'AIE-' || substr(replace(e.id::text, '-', ''), 1, 16),
          e.conversation_id,
          e.user_id,
          'ai_safety_escalation',
          CASE WHEN e.severity >= 3 THEN 'urgent'
               WHEN e.severity = 2 THEN 'high'
               ELSE 'normal' END,
          e.reason_code,
          CASE WHEN e.severity >= 3 THEN 'critical'
               WHEN e.severity = 2 THEN 'high'
               ELSE 'standard' END,
          CASE WHEN e.status = 'open' THEN 'pending_assignment' ELSE e.status END,
          'safety',
          'system_initiated',
          e.dedupe_key,
          e.geography_code,
          e.runbook_id,
          e.severity,
          e.opened_at,
          e.acknowledged_at,
          e.resolved_at
        FROM ai_human_escalations e
        WHERE EXISTS (SELECT 1 FROM ai_conversations c WHERE c.id = e.conversation_id)
        ON CONFLICT (idempotency_key) DO NOTHING;
        """
    )

    # Any escalation whose conversation no longer exists cannot satisfy the
    # target's foreign key. Dropping it silently would lose a safety record, so
    # it is parked in a quarantine table for a human to look at.
    _run(
        """
        CREATE TABLE IF NOT EXISTS ai_human_escalation_orphans (
          id UUID PRIMARY KEY,
          user_id UUID,
          conversation_id UUID,
          reason_code VARCHAR(128),
          severity INTEGER,
          status VARCHAR(16),
          geography_code VARCHAR(8),
          dedupe_key VARCHAR(255),
          opened_at TIMESTAMPTZ,
          quarantined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          quarantine_reason TEXT NOT NULL DEFAULT 'conversation_missing'
        );

        INSERT INTO ai_human_escalation_orphans
          (id, user_id, conversation_id, reason_code, severity, status, geography_code,
           dedupe_key, opened_at)
        SELECT e.id, e.user_id, e.conversation_id, e.reason_code, e.severity, e.status,
               e.geography_code, e.dedupe_key, e.opened_at
        FROM ai_human_escalations e
        WHERE NOT EXISTS (SELECT 1 FROM ai_conversations c WHERE c.id = e.conversation_id)
        ON CONFLICT (id) DO NOTHING;

        DROP TABLE IF EXISTS ai_human_escalations;
        """
    )


def downgrade() -> None:
    # The merged rows are deliberately NOT unmerged: they are now part of the
    # established queue and may have been assigned or resolved there. Recreating
    # the table empty restores the schema shape without inventing history.
    _run(
        """
        -- Recreated to match migration 0103's definition column for column.
        -- An approximation is not good enough here: this migration's own
        -- upgrade reads ``e.opened_at``, so a downgrade that recreated the
        -- table with ``created_at`` made rollback-then-retry fail with
        -- "column e.opened_at does not exist" — which is precisely the moment
        -- an operator is least able to absorb a second failure.
        CREATE TABLE IF NOT EXISTS ai_human_escalations (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id UUID NOT NULL REFERENCES users(id),
          conversation_id UUID NOT NULL,
          reason_code VARCHAR(128) NOT NULL,
          severity INTEGER NOT NULL DEFAULT 0,
          status VARCHAR(16) NOT NULL DEFAULT 'open',
          geography_code VARCHAR(8),
          runbook_id UUID REFERENCES ai_escalation_runbooks(id),
          handled_by UUID REFERENCES users(id),
          resolution_note TEXT,
          dedupe_key VARCHAR(255) NOT NULL,
          opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          acknowledged_at TIMESTAMPTZ,
          resolved_at TIMESTAMPTZ,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (dedupe_key),
          CHECK (status IN ('open','acknowledged','resolved','cancelled')),
          CHECK (severity BETWEEN 0 AND 10),
          CHECK (status <> 'acknowledged' OR acknowledged_at IS NOT NULL),
          CHECK (status NOT IN ('resolved','cancelled') OR resolved_at IS NOT NULL)
        );

        CREATE INDEX IF NOT EXISTS ai_human_escalations_queue_idx
          ON ai_human_escalations (severity DESC, opened_at)
          WHERE status IN ('open','acknowledged');

        DROP INDEX IF EXISTS ai_human_referrals_open_idx;

        ALTER TABLE ai_human_referrals
          DROP COLUMN IF EXISTS severity,
          DROP COLUMN IF EXISTS runbook_id,
          DROP COLUMN IF EXISTS geography_code;

        -- ai_human_escalation_orphans is deliberately retained. Those rows
        -- could not satisfy ai_human_referrals.conversation_id and are safety
        -- records, not disposable migration scratch data. Downgrade restores
        -- 0103's writable queue shape but does not pretend an absent parent
        -- conversation has reappeared or silently discard the quarantine.
        """
    )
