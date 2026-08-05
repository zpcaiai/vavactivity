"""Add offline evaluation datasets, evaluation runs and guarded experiments.

Revision ID: 20260804_0059
Revises: 20260804_0058
"""

# ruff: noqa: E501

from alembic import op

revision = "20260804_0059"
down_revision = "20260804_0058"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE recommendation_evaluation_datasets (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      dataset_code VARCHAR(128) NOT NULL UNIQUE,
      name VARCHAR(300) NOT NULL,
      status VARCHAR(32) NOT NULL DEFAULT 'active',
      version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
      fixture_manifest JSONB NOT NULL,
      privacy_review_status VARCHAR(32) NOT NULL DEFAULT 'synthetic_only',
      created_by UUID REFERENCES users(id),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE TABLE recommendation_evaluation_runs (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      dataset_id UUID NOT NULL REFERENCES recommendation_evaluation_datasets(id),
      strategy_id UUID NOT NULL REFERENCES recommendation_strategies(id),
      status VARCHAR(32) NOT NULL DEFAULT 'pending',
      metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
      blocking_failures JSONB NOT NULL DEFAULT '[]'::jsonb,
      guardrail_failures JSONB NOT NULL DEFAULT '[]'::jsonb,
      approved_by UUID REFERENCES users(id),
      approved_at TIMESTAMPTZ,
      started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      completed_at TIMESTAMPTZ
    );
    CREATE INDEX ix_recommendation_evaluation_strategy ON recommendation_evaluation_runs(strategy_id, started_at DESC);

    CREATE TABLE recommendation_experiments (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      experiment_code VARCHAR(128) NOT NULL UNIQUE,
      name VARCHAR(300) NOT NULL,
      hypothesis TEXT NOT NULL,
      status VARCHAR(32) NOT NULL DEFAULT 'draft',
      control_strategy_id UUID NOT NULL REFERENCES recommendation_strategies(id),
      treatment_strategy_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
      eligibility_definition JSONB NOT NULL DEFAULT '{}'::jsonb,
      allocation_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
      primary_metrics JSONB NOT NULL DEFAULT '[]'::jsonb,
      guardrail_metrics JSONB NOT NULL DEFAULT '[]'::jsonb,
      guardrail_thresholds JSONB NOT NULL DEFAULT '{}'::jsonb,
      stop_reason VARCHAR(128),
      starts_at TIMESTAMPTZ,
      ends_at TIMESTAMPTZ,
      created_by UUID REFERENCES users(id),
      approved_by UUID REFERENCES users(id),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      approved_at TIMESTAMPTZ
    );

    CREATE TABLE recommendation_experiment_assignments (
      experiment_id UUID NOT NULL REFERENCES recommendation_experiments(id) ON DELETE CASCADE,
      user_id UUID NOT NULL REFERENCES users(id),
      variant_code VARCHAR(128) NOT NULL,
      assignment_hash VARCHAR(128) NOT NULL,
      assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY(experiment_id, user_id)
    );
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE recommendation_experiment_assignments;
    DROP TABLE recommendation_experiments;
    DROP TABLE recommendation_evaluation_runs;
    DROP TABLE recommendation_evaluation_datasets;
    """)
