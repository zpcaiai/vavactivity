# ruff: noqa: E501

"""Member dashboard preferences, dismissals, degradation log and route overrides.

Covers DASH-001.

What this migration deliberately does *not* create: a materialized dashboard
table. Every number the dashboard shows is owned by another module, and a copy
would be a second source of truth that drifts. The dashboard reads the source
tables through the same predicates the source modules use; the tables below hold
only the things the dashboard genuinely owns - a member's display preferences,
their dismissals, the operator's route overrides, and a log of which sections
degraded.

``member_dashboard_task_type_overrides`` ships **empty**: the deep-link
templates live in ``member_dashboard.domain.DEEP_LINK_TEMPLATES`` so a fresh
deployment routes correctly with no data, and this table exists for the case
where a route has to move without a deploy.

Revision ID: 20260812_0102
Revises: 20260812_0101
"""

import re

from alembic import op

revision = "20260812_0102"
down_revision = "20260812_0101"
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
        CREATE TABLE member_dashboard_preferences (
          user_id UUID PRIMARY KEY REFERENCES users(id),
          -- Display only. Hiding a section never changes what the member is
          -- authorized to see; authorization is resolved per request.
          hidden_sections JSONB NOT NULL DEFAULT '[]'::jsonb,
          page_size INTEGER NOT NULL DEFAULT 20,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (page_size BETWEEN 1 AND 100),
          CHECK (jsonb_typeof(hidden_sections) = 'array')
        );

        -- A dismissal hides a card. It never completes the underlying task:
        -- the survey is still due, it is simply off the home screen.
        CREATE TABLE member_dashboard_task_dismissals (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id UUID NOT NULL REFERENCES users(id),
          task_type VARCHAR(64) NOT NULL,
          task_key VARCHAR(128) NOT NULL,
          dismissed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (user_id, task_key),
          CHECK (task_type IN ('survey_pending','mutual_selection_pending','result_letter_unread','registration_upcoming','matchmaking_attempt_available','notification_unread')),
          -- The key must name its own type, so a dismissal cannot be forged
          -- against a different section's row.
          CHECK (task_key LIKE task_type || ':%')
        );
        CREATE INDEX member_dashboard_task_dismissals_user_idx
          ON member_dashboard_task_dismissals (user_id, task_type);

        -- Append-only record of degraded sections. Without it, "the dashboard
        -- looked empty this morning" is unanswerable: a gracefully degraded
        -- section is by design indistinguishable from an empty one at the API.
        CREATE TABLE member_dashboard_section_incidents (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id UUID REFERENCES users(id),
          section_key VARCHAR(32) NOT NULL,
          error_code VARCHAR(64) NOT NULL,
          error_detail TEXT,
          occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (section_key IN ('survey_tasks','result_letters','registrations','mutual_selection','matchmaking','notifications'))
        );
        CREATE INDEX member_dashboard_section_incidents_recent_idx
          ON member_dashboard_section_incidents (section_key, occurred_at DESC);

        -- Ships empty; code defaults apply until a row exists. The CHECK keeps
        -- an override site-relative, so a bad row cannot turn a dashboard card
        -- into an off-site redirect. The application re-validates on render.
        CREATE TABLE member_dashboard_task_type_overrides (
          task_type VARCHAR(64) PRIMARY KEY,
          deep_link_template VARCHAR(255) NOT NULL,
          base_priority VARCHAR(16) NOT NULL DEFAULT 'normal',
          is_active BOOLEAN NOT NULL DEFAULT true,
          updated_by UUID REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (task_type IN ('survey_pending','mutual_selection_pending','result_letter_unread','registration_upcoming','matchmaking_attempt_available','notification_unread')),
          CHECK (base_priority IN ('urgent','high','normal','low')),
          CHECK (deep_link_template LIKE '/%' AND deep_link_template NOT LIKE '//%')
        );
        """
    )

    # Supporting indexes on the *source* tables. The dashboard's fan-out is one
    # query per section per member, so each of them must be a single index hit.
    _run(
        """
        CREATE INDEX IF NOT EXISTS survey_tasks_dashboard_idx
          ON survey_tasks (user_id, due_at) WHERE status IN ('pending','in_progress');
        CREATE INDEX IF NOT EXISTS result_letters_unread_idx
          ON result_letters (recipient_user_id) WHERE status = 'published' AND read_at IS NULL;
        """
    )


def downgrade() -> None:
    _run(
        """
        DROP INDEX IF EXISTS result_letters_unread_idx;
        DROP INDEX IF EXISTS survey_tasks_dashboard_idx;
        DROP TABLE IF EXISTS member_dashboard_task_type_overrides;
        DROP TABLE IF EXISTS member_dashboard_section_incidents;
        DROP TABLE IF EXISTS member_dashboard_task_dismissals;
        DROP TABLE IF EXISTS member_dashboard_preferences;
        """
    )
