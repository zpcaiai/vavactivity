"""Create scoped restrictions and approved case decisions.

Revision ID: 20260805_0081
Revises: 20260805_0080
"""

# ruff: noqa: E501

from alembic import op

revision = "20260805_0081"
down_revision = "20260805_0080"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE safety_case_decisions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), safety_case_id UUID NOT NULL REFERENCES safety_cases(id),
      decision_type VARCHAR(64) NOT NULL, decision_scope JSONB NOT NULL, reason_codes JSONB NOT NULL,
      evidence_item_ids JSONB NOT NULL, user_message_safe TEXT, internal_rationale_encrypted TEXT NOT NULL,
      restriction_manifest JSONB NOT NULL DEFAULT '[]'::jsonb, decided_by UUID NOT NULL REFERENCES users(id),
      approved_by UUID REFERENCES users(id), decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      appeal_allowed BOOLEAN NOT NULL, supersedes_decision_id UUID REFERENCES safety_case_decisions(id),
      CHECK (approved_by IS NULL OR approved_by <> decided_by)
    );
    ALTER TABLE safety_cases ADD CONSTRAINT fk_safety_case_current_decision FOREIGN KEY (current_decision_id) REFERENCES safety_case_decisions(id);
    CREATE TABLE account_restrictions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL REFERENCES users(id),
      restriction_type VARCHAR(64) NOT NULL, scope_definition JSONB NOT NULL, status VARCHAR(32) NOT NULL DEFAULT 'pending_approval',
      source_type VARCHAR(32) NOT NULL, source_reference_id UUID, reason_code VARCHAR(128) NOT NULL,
      user_message_safe TEXT, internal_reason_encrypted TEXT, starts_at TIMESTAMPTZ NOT NULL,
      ends_at TIMESTAMPTZ, appeal_allowed BOOLEAN NOT NULL DEFAULT TRUE, imposed_by UUID REFERENCES users(id),
      approved_by UUID REFERENCES users(id), lifted_by UUID REFERENCES users(id), lifted_at TIMESTAMPTZ,
      lift_reason_encrypted TEXT, version INTEGER NOT NULL DEFAULT 1,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CHECK (status IN ('pending_approval','active','expired','lifted','rejected')),
      CHECK (ends_at IS NULL OR ends_at > starts_at),
      CHECK (approved_by IS NULL OR approved_by <> imposed_by)
    );
    CREATE INDEX ix_account_restrictions_active ON account_restrictions(user_id,status,restriction_type,ends_at);
    CREATE TABLE safety_inbox_events (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), source_module VARCHAR(64) NOT NULL,
      event_type VARCHAR(128) NOT NULL, event_version VARCHAR(32) NOT NULL,
      source_event_id VARCHAR(200) NOT NULL, payload JSONB NOT NULL, status VARCHAR(32) NOT NULL DEFAULT 'received',
      received_at TIMESTAMPTZ NOT NULL DEFAULT now(), processed_at TIMESTAMPTZ,
      UNIQUE(source_module,source_event_id)
    );
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE safety_inbox_events;
    DROP TABLE account_restrictions;
    ALTER TABLE safety_cases DROP CONSTRAINT fk_safety_case_current_decision;
    DROP TABLE safety_case_decisions;
    """)
