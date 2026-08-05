"""Create membership audit and reconciliation records.

Revision ID: 20260805_0076
Revises: 20260805_0075
"""

# ruff: noqa: E501

from alembic import op

revision = "20260805_0076"
down_revision = "20260805_0075"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE membership_audit_events (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      actor_user_id UUID REFERENCES users(id),
      membership_account_id UUID REFERENCES membership_accounts(id),
      event_type VARCHAR(128) NOT NULL,
      reason_code VARCHAR(128),
      safe_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
      request_id UUID,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE membership_reconciliation_issues (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id UUID NOT NULL REFERENCES users(id),
      membership_account_id UUID REFERENCES membership_accounts(id),
      issue_code VARCHAR(128) NOT NULL,
      severity VARCHAR(32) NOT NULL,
      source_snapshot JSONB NOT NULL,
      status VARCHAR(32) NOT NULL DEFAULT 'open',
      detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      resolved_at TIMESTAMPTZ,
      resolved_by UUID REFERENCES users(id),
      resolution_summary TEXT,
      CHECK (severity IN ('info','warning','error','critical')),
      CHECK (status IN ('open','investigating','resolved','ignored'))
    );
    CREATE UNIQUE INDEX uq_membership_open_reconciliation_issue ON membership_reconciliation_issues(user_id, membership_account_id, issue_code) WHERE status IN ('open','investigating');
    CREATE INDEX ix_membership_audit_account ON membership_audit_events(membership_account_id, created_at DESC);
    CREATE INDEX ix_membership_reconciliation_open ON membership_reconciliation_issues(status, severity, detected_at);
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE membership_reconciliation_issues;
    DROP TABLE membership_audit_events;
    """)
