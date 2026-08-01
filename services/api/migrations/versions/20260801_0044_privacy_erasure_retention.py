"""Add privacy erasure, retention and holds.

Revision ID: 20260801_0044
Revises: 20260801_0043
"""

# ruff: noqa: E501

from alembic import op

revision = "20260801_0044"
down_revision = "20260801_0043"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE privacy_erasure_plans (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), data_subject_request_id UUID NOT NULL UNIQUE REFERENCES data_subject_requests(id),
      user_id UUID NOT NULL REFERENCES users(id), status VARCHAR(32) NOT NULL, module_plans JSONB NOT NULL,
      blocking_conditions JSONB NOT NULL DEFAULT '[]'::jsonb, retention_exceptions JSONB NOT NULL DEFAULT '[]'::jsonb,
      user_confirmation_required BOOLEAN NOT NULL, user_confirmed_at TIMESTAMPTZ, planned_at TIMESTAMPTZ NOT NULL,
      approved_by UUID REFERENCES users(id), approved_at TIMESTAMPTZ, execution_started_at TIMESTAMPTZ,
      completed_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE privacy_erasure_jobs (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), erasure_plan_id UUID NOT NULL REFERENCES privacy_erasure_plans(id),
      module_code VARCHAR(64) NOT NULL, operation_type VARCHAR(32) NOT NULL, status VARCHAR(32) NOT NULL,
      idempotency_key VARCHAR(128) NOT NULL UNIQUE, result_summary JSONB,
      retained_asset_manifest JSONB NOT NULL DEFAULT '[]'::jsonb, attempts INTEGER NOT NULL DEFAULT 0,
      next_attempt_at TIMESTAMPTZ, started_at TIMESTAMPTZ, completed_at TIMESTAMPTZ,
      error_code VARCHAR(128), created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(erasure_plan_id,module_code,operation_type)
    );
    CREATE TABLE privacy_retention_policies (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), policy_code VARCHAR(128) NOT NULL,
      semantic_version VARCHAR(64) NOT NULL, data_category VARCHAR(64) NOT NULL, module_code VARCHAR(64) NOT NULL,
      trigger_event VARCHAR(128) NOT NULL, retention_days INTEGER CHECK(retention_days IS NULL OR retention_days>=0),
      expiration_action VARCHAR(32) NOT NULL, policy_basis TEXT NOT NULL, exceptions JSONB NOT NULL DEFAULT '[]'::jsonb,
      status VARCHAR(32) NOT NULL, approved_by UUID NOT NULL REFERENCES users(id), approved_at TIMESTAMPTZ NOT NULL,
      valid_from TIMESTAMPTZ NOT NULL, valid_until TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(policy_code,semantic_version)
    );
    CREATE UNIQUE INDEX uq_active_retention_policy ON privacy_retention_policies(policy_code) WHERE status='active';
    CREATE TABLE privacy_retention_instances (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), policy_id UUID NOT NULL REFERENCES privacy_retention_policies(id),
      subject_type VARCHAR(64) NOT NULL, subject_id UUID NOT NULL, user_id UUID REFERENCES users(id),
      trigger_at TIMESTAMPTZ NOT NULL, expires_at TIMESTAMPTZ, status VARCHAR(32) NOT NULL,
      active_hold_count INTEGER NOT NULL DEFAULT 0, evaluated_at TIMESTAMPTZ, action_completed_at TIMESTAMPTZ,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(policy_id,subject_type,subject_id)
    );
    CREATE INDEX ix_retention_due ON privacy_retention_instances(status,expires_at);
    CREATE TABLE privacy_legal_holds (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), hold_number VARCHAR(64) NOT NULL UNIQUE,
      hold_type VARCHAR(32) NOT NULL, status VARCHAR(32) NOT NULL, scope_definition_encrypted TEXT NOT NULL,
      reason_encrypted TEXT NOT NULL, authorized_by UUID NOT NULL REFERENCES users(id),
      created_by UUID NOT NULL REFERENCES users(id), starts_at TIMESTAMPTZ NOT NULL, ends_at TIMESTAMPTZ,
      released_by UUID REFERENCES users(id), released_at TIMESTAMPTZ, release_reason_encrypted TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE privacy_legal_holds;
    DROP TABLE privacy_retention_instances;
    DROP TABLE privacy_retention_policies;
    DROP TABLE privacy_erasure_jobs;
    DROP TABLE privacy_erasure_plans;
    """)
