"""Create versioned moderation and behavioral-signal records.

Revision ID: 20260805_0079
Revises: 20260805_0078
"""

# ruff: noqa: E501

from alembic import op

revision = "20260805_0079"
down_revision = "20260805_0078"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE moderation_tasks (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), target_type VARCHAR(64) NOT NULL,
      target_reference_id UUID NOT NULL, target_version VARCHAR(128) NOT NULL,
      status VARCHAR(32) NOT NULL DEFAULT 'pending', priority VARCHAR(32) NOT NULL DEFAULT 'normal',
      policy_version VARCHAR(64) NOT NULL, automated_result_id UUID, assigned_to UUID REFERENCES users(id),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), completed_at TIMESTAMPTZ,
      UNIQUE(target_type,target_reference_id,target_version)
    );
    CREATE TABLE moderation_automated_results (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), moderation_task_id UUID NOT NULL REFERENCES moderation_tasks(id),
      provider VARCHAR(64) NOT NULL, model_name VARCHAR(200), model_revision VARCHAR(128),
      category_scores JSONB NOT NULL, detected_patterns JSONB NOT NULL DEFAULT '[]'::jsonb,
      recommendation VARCHAR(32) NOT NULL, confidence_basis_points INTEGER NOT NULL,
      input_checksum VARCHAR(128) NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CHECK (confidence_basis_points BETWEEN 0 AND 10000)
    );
    ALTER TABLE moderation_tasks ADD CONSTRAINT fk_moderation_automated_result FOREIGN KEY (automated_result_id) REFERENCES moderation_automated_results(id);
    CREATE TABLE moderation_decisions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), moderation_task_id UUID NOT NULL REFERENCES moderation_tasks(id),
      decision VARCHAR(32) NOT NULL, category_codes JSONB NOT NULL, reason_code VARCHAR(128),
      user_message_safe TEXT, internal_note_encrypted TEXT, decided_by UUID NOT NULL REFERENCES users(id),
      decided_at TIMESTAMPTZ NOT NULL DEFAULT now(), policy_version VARCHAR(64) NOT NULL,
      CHECK (decision IN ('approve','reject','limit','remove','escalate'))
    );
    CREATE TABLE safety_behavior_aggregates (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL REFERENCES users(id),
      metric_code VARCHAR(128) NOT NULL, window_type VARCHAR(32) NOT NULL,
      window_starts_at TIMESTAMPTZ NOT NULL, window_ends_at TIMESTAMPTZ NOT NULL,
      event_count BIGINT NOT NULL, distinct_target_count BIGINT NOT NULL DEFAULT 0,
      aggregation_version VARCHAR(64) NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(user_id,metric_code,window_starts_at)
    );
    CREATE TABLE fraud_signals (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), subject_user_id UUID NOT NULL REFERENCES users(id),
      signal_code VARCHAR(128) NOT NULL, signal_source VARCHAR(64) NOT NULL, severity VARCHAR(32) NOT NULL,
      confidence_basis_points INTEGER, source_reference_type VARCHAR(64), source_reference_id UUID,
      signal_snapshot_encrypted JSONB NOT NULL, status VARCHAR(32) NOT NULL DEFAULT 'active',
      detected_at TIMESTAMPTZ NOT NULL DEFAULT now(), expires_at TIMESTAMPTZ,
      UNIQUE(subject_user_id,signal_code,signal_source,source_reference_id),
      CHECK (confidence_basis_points IS NULL OR confidence_basis_points BETWEEN 0 AND 10000)
    );
    CREATE INDEX ix_moderation_queue ON moderation_tasks(status,priority,created_at);
    CREATE INDEX ix_fraud_signals_subject ON fraud_signals(subject_user_id,status,detected_at DESC);
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE fraud_signals;
    DROP TABLE safety_behavior_aggregates;
    DROP TABLE moderation_decisions;
    ALTER TABLE moderation_tasks DROP CONSTRAINT fk_moderation_automated_result;
    DROP TABLE moderation_automated_results;
    DROP TABLE moderation_tasks;
    """)
