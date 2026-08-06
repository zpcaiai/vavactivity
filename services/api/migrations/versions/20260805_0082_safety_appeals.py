"""Create independent appeals, remediation and red-team runs.

Revision ID: 20260805_0082
Revises: 20260805_0081
"""

# ruff: noqa: E501

from alembic import op

revision = "20260805_0082"
down_revision = "20260805_0081"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE safety_appeals (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), appeal_number VARCHAR(64) NOT NULL UNIQUE,
      appellant_user_id UUID NOT NULL REFERENCES users(id), restriction_id UUID REFERENCES account_restrictions(id),
      safety_case_id UUID REFERENCES safety_cases(id), decision_id UUID REFERENCES safety_case_decisions(id),
      status VARCHAR(32) NOT NULL DEFAULT 'submitted', appeal_reason_encrypted TEXT NOT NULL,
      evidence_manifest JSONB NOT NULL DEFAULT '[]'::jsonb, submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      review_due_at TIMESTAMPTZ, assigned_to UUID REFERENCES users(id), outcome VARCHAR(32),
      outcome_message_safe TEXT, internal_review_encrypted TEXT, decided_by UUID REFERENCES users(id),
      decided_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), version INTEGER NOT NULL DEFAULT 1,
      CHECK (status IN ('submitted','eligibility_review','assigned','in_review','decided','closed','ineligible')),
      CHECK (outcome IS NULL OR outcome IN ('upheld','modified','overturned','ineligible')),
      CHECK (restriction_id IS NOT NULL OR decision_id IS NOT NULL)
    );
    CREATE UNIQUE INDEX uq_open_safety_appeal ON safety_appeals(appellant_user_id,restriction_id) WHERE status NOT IN ('decided','closed','ineligible');
    CREATE UNIQUE INDEX uq_open_safety_decision_appeal ON safety_appeals(appellant_user_id,decision_id) WHERE restriction_id IS NULL AND status NOT IN ('decided','closed','ineligible');
    CREATE TABLE safety_remediations (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), appeal_id UUID NOT NULL REFERENCES safety_appeals(id),
      superseding_decision_id UUID REFERENCES safety_case_decisions(id), action_manifest JSONB NOT NULL,
      status VARCHAR(32) NOT NULL DEFAULT 'pending', executed_by UUID REFERENCES users(id),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), completed_at TIMESTAMPTZ,
      UNIQUE(appeal_id)
    );
    CREATE TABLE safety_red_team_runs (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), run_number VARCHAR(64) NOT NULL UNIQUE,
      policy_version VARCHAR(64) NOT NULL, status VARCHAR(32) NOT NULL DEFAULT 'running',
      fixture_manifest JSONB NOT NULL, result_manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
      block_bypass_count INTEGER NOT NULL DEFAULT 0, contact_leakage_count INTEGER NOT NULL DEFAULT 0,
      started_by UUID NOT NULL REFERENCES users(id), completed_by UUID REFERENCES users(id),
      approved_by UUID REFERENCES users(id), started_at TIMESTAMPTZ NOT NULL DEFAULT now(), completed_at TIMESTAMPTZ,
      CHECK (status IN ('running','passed','failed','approved','release_blocked')),
      CHECK (block_bypass_count >= 0 AND contact_leakage_count >= 0),
      CHECK (approved_by IS NULL OR approved_by <> started_by)
    );
    CREATE INDEX ix_safety_appeals_queue ON safety_appeals(status,review_due_at);
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE safety_red_team_runs;
    DROP TABLE safety_remediations;
    DROP TABLE safety_appeals;
    """)
