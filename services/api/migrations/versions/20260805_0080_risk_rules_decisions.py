"""Create governed safety rules and immutable risk decisions.

Revision ID: 20260805_0080
Revises: 20260805_0079
"""

# ruff: noqa: E501

from alembic import op

revision = "20260805_0080"
down_revision = "20260805_0079"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE safety_risk_rules (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), rule_code VARCHAR(128) NOT NULL,
      semantic_version VARCHAR(64) NOT NULL, category VARCHAR(64) NOT NULL, rule_type VARCHAR(32) NOT NULL,
      condition_schema JSONB NOT NULL, condition_definition JSONB NOT NULL, action_definition JSONB NOT NULL,
      severity VARCHAR(32) NOT NULL, score_delta INTEGER NOT NULL DEFAULT 0, status VARCHAR(32) NOT NULL DEFAULT 'draft',
      applicable_modules JSONB NOT NULL, rollout_basis_points INTEGER NOT NULL DEFAULT 10000,
      created_by UUID NOT NULL REFERENCES users(id), approved_by UUID REFERENCES users(id),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), approved_at TIMESTAMPTZ, activated_at TIMESTAMPTZ,
      retired_at TIMESTAMPTZ, supersedes_rule_id UUID REFERENCES safety_risk_rules(id),
      UNIQUE(rule_code,semantic_version),
      CHECK (rule_type IN ('deterministic','rate','sequence','content_classifier','aggregate','manual_flag')),
      CHECK (status IN ('draft','pending_approval','approved','active','retired','rolled_back')),
      CHECK (rollout_basis_points BETWEEN 0 AND 10000),
      CHECK (approved_by IS NULL OR approved_by <> created_by)
    );
    CREATE UNIQUE INDEX uq_safety_active_rule ON safety_risk_rules(rule_code) WHERE status='active';
    CREATE TABLE safety_risk_decisions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), subject_user_id UUID REFERENCES users(id),
      target_type VARCHAR(64), target_reference_id UUID, decision_context VARCHAR(64) NOT NULL,
      risk_level VARCHAR(32) NOT NULL, risk_score INTEGER NOT NULL, rule_hits JSONB NOT NULL,
      model_signals JSONB NOT NULL DEFAULT '[]'::jsonb, decision VARCHAR(32) NOT NULL,
      reason_codes JSONB NOT NULL, policy_version VARCHAR(64) NOT NULL, restriction_version INTEGER NOT NULL DEFAULT 1,
      valid_until TIMESTAMPTZ, human_review_required BOOLEAN NOT NULL DEFAULT FALSE,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CHECK (risk_level IN ('none','low','moderate','high','critical')),
      CHECK (decision IN ('allow','allow_with_monitoring','rate_limit','content_hold','interaction_freeze','require_reverification','temporary_restriction','human_review_required','deny'))
    );
    CREATE INDEX ix_safety_decisions_subject ON safety_risk_decisions(subject_user_id,created_at DESC);
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE safety_risk_decisions;
    DROP TABLE safety_risk_rules;
    """)
