"""Add recommendation evaluation datasets, runs and governed experiments.

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
      status VARCHAR(32) NOT NULL,
      version INTEGER NOT NULL DEFAULT 1,
      fixture_manifest JSONB NOT NULL,
      synthetic_only BOOLEAN NOT NULL DEFAULT true,
      privacy_review_status VARCHAR(32) NOT NULL DEFAULT 'pending',
      created_by UUID NOT NULL REFERENCES users(id),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE recommendation_evaluation_runs (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      dataset_id UUID NOT NULL REFERENCES recommendation_evaluation_datasets(id),
      strategy_id UUID NOT NULL REFERENCES recommendation_strategies(id),
      status VARCHAR(32) NOT NULL,
      correctness_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
      ranking_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
      coverage_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
      fairness_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
      guardrail_failures JSONB NOT NULL DEFAULT '[]'::jsonb,
      passed BOOLEAN,
      started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      completed_at TIMESTAMPTZ,
      approved_by UUID REFERENCES users(id),
      approved_at TIMESTAMPTZ
    );
    CREATE INDEX ix_recommendation_evaluation_runs_strategy ON recommendation_evaluation_runs(strategy_id, started_at DESC);
    CREATE TABLE recommendation_experiments (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      experiment_code VARCHAR(128) NOT NULL UNIQUE,
      name VARCHAR(300) NOT NULL,
      hypothesis TEXT NOT NULL,
      status VARCHAR(32) NOT NULL,
      control_strategy_id UUID NOT NULL REFERENCES recommendation_strategies(id),
      treatment_strategy_ids JSONB NOT NULL,
      eligibility_definition JSONB NOT NULL,
      allocation_policy JSONB NOT NULL,
      primary_metrics JSONB NOT NULL,
      guardrail_metrics JSONB NOT NULL,
      starts_at TIMESTAMPTZ,
      ends_at TIMESTAMPTZ,
      stop_reason TEXT,
      created_by UUID NOT NULL REFERENCES users(id),
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
    # An experiment can only start once it is approved.
    op.execute("""
    CREATE FUNCTION require_recommendation_experiment_approval() RETURNS trigger AS $$
    BEGIN
      IF NEW.status='running' AND NEW.approved_by IS NULL THEN
        RAISE EXCEPTION 'a recommendation experiment requires approval before it can run';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """)
    op.execute(
        "CREATE TRIGGER recommendation_experiment_gate BEFORE INSERT OR UPDATE ON recommendation_experiments FOR EACH ROW EXECUTE FUNCTION require_recommendation_experiment_approval()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS recommendation_experiment_gate ON recommendation_experiments"
    )
    op.execute("DROP FUNCTION IF EXISTS require_recommendation_experiment_approval")
    _run("""
    DROP TABLE recommendation_experiment_assignments;
    DROP TABLE recommendation_experiments;
    DROP TABLE recommendation_evaluation_runs;
    DROP TABLE recommendation_evaluation_datasets;
    """)
