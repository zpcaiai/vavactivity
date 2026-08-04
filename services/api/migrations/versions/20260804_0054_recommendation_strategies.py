"""Add versioned recommendation strategies and feature definitions.

Revision ID: 20260804_0054
Revises: 20260804_0053
"""

# ruff: noqa: E501

from alembic import op

revision = "20260804_0054"
down_revision = "20260804_0053"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE recommendation_strategies (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      strategy_code VARCHAR(128) NOT NULL,
      semantic_version VARCHAR(64) NOT NULL,
      status VARCHAR(32) NOT NULL,
      hard_constraint_policy JSONB NOT NULL,
      feature_manifest JSONB NOT NULL,
      scoring_policy JSONB NOT NULL,
      bidirectional_policy JSONB NOT NULL,
      ranking_policy JSONB NOT NULL,
      diversification_policy JSONB NOT NULL,
      exposure_policy JSONB NOT NULL,
      explanation_policy JSONB NOT NULL,
      cold_start_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
      applicable_regions JSONB NOT NULL DEFAULT '[]'::jsonb,
      applicable_segments JSONB NOT NULL DEFAULT '[]'::jsonb,
      evaluation_passed BOOLEAN NOT NULL DEFAULT false,
      created_by UUID NOT NULL REFERENCES users(id),
      approved_by UUID REFERENCES users(id),
      activated_by UUID REFERENCES users(id),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      approved_at TIMESTAMPTZ,
      activated_at TIMESTAMPTZ,
      UNIQUE(strategy_code, semantic_version)
    );
    CREATE UNIQUE INDEX uq_active_recommendation_strategy ON recommendation_strategies(strategy_code) WHERE status='active';
    CREATE TABLE recommendation_feature_definitions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      feature_code VARCHAR(128) NOT NULL,
      semantic_version VARCHAR(64) NOT NULL,
      feature_group VARCHAR(64) NOT NULL,
      value_schema JSONB NOT NULL,
      scoring_function_code VARCHAR(128) NOT NULL,
      sensitivity VARCHAR(32) NOT NULL,
      explainable BOOLEAN NOT NULL DEFAULT true,
      user_configurable BOOLEAN NOT NULL DEFAULT false,
      status VARCHAR(32) NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(feature_code, semantic_version)
    );
    CREATE TABLE recommendation_audit_events (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      event_type VARCHAR(128) NOT NULL,
      actor_id UUID REFERENCES users(id),
      subject_type VARCHAR(64) NOT NULL,
      subject_id UUID,
      reason TEXT,
      safe_context JSONB NOT NULL DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_recommendation_audit_subject ON recommendation_audit_events(subject_type, subject_id, created_at DESC);
    CREATE INDEX ix_recommendation_audit_type ON recommendation_audit_events(event_type, created_at DESC);
    """)
    op.execute("""
    CREATE FUNCTION protect_active_recommendation_strategy() RETURNS trigger AS $$
    BEGIN
      IF OLD.status='active' AND (
        NEW.hard_constraint_policy IS DISTINCT FROM OLD.hard_constraint_policy
        OR NEW.feature_manifest IS DISTINCT FROM OLD.feature_manifest
        OR NEW.scoring_policy IS DISTINCT FROM OLD.scoring_policy
        OR NEW.bidirectional_policy IS DISTINCT FROM OLD.bidirectional_policy
        OR NEW.ranking_policy IS DISTINCT FROM OLD.ranking_policy
        OR NEW.semantic_version IS DISTINCT FROM OLD.semantic_version) THEN
        RAISE EXCEPTION 'active recommendation strategy content is immutable';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """)
    op.execute(
        "CREATE TRIGGER recommendation_strategy_immutable BEFORE UPDATE ON recommendation_strategies FOR EACH ROW EXECUTE FUNCTION protect_active_recommendation_strategy()"
    )
    # A strategy can only be activated after evaluation and approval.
    op.execute("""
    CREATE FUNCTION require_recommendation_strategy_gates() RETURNS trigger AS $$
    BEGIN
      IF NEW.status='active' AND (NEW.approved_by IS NULL OR NEW.evaluation_passed IS NOT TRUE) THEN
        RAISE EXCEPTION 'a recommendation strategy requires approval and a passing evaluation before activation';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """)
    op.execute(
        "CREATE TRIGGER recommendation_strategy_release_gate BEFORE INSERT OR UPDATE ON recommendation_strategies FOR EACH ROW EXECUTE FUNCTION require_recommendation_strategy_gates()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS recommendation_strategy_release_gate ON recommendation_strategies"
    )
    op.execute("DROP FUNCTION IF EXISTS require_recommendation_strategy_gates")
    op.execute(
        "DROP TRIGGER IF EXISTS recommendation_strategy_immutable ON recommendation_strategies"
    )
    op.execute("DROP FUNCTION IF EXISTS protect_active_recommendation_strategy")
    _run("""
    DROP TABLE recommendation_audit_events;
    DROP TABLE recommendation_feature_definitions;
    DROP TABLE recommendation_strategies;
    """)
