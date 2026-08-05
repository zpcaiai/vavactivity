"""Create governed membership benefit registry.

Revision ID: 20260805_0072
Revises: 20260805_0071
"""

# ruff: noqa: E501

from alembic import op

revision = "20260805_0072"
down_revision = "20260805_0071"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE membership_benefit_definitions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      benefit_code VARCHAR(128) NOT NULL,
      semantic_version VARCHAR(64) NOT NULL,
      benefit_type VARCHAR(32) NOT NULL,
      value_schema JSONB NOT NULL,
      owning_module VARCHAR(64) NOT NULL,
      sensitivity VARCHAR(32) NOT NULL DEFAULT 'internal',
      status VARCHAR(32) NOT NULL DEFAULT 'active',
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(benefit_code, semantic_version),
      CHECK (benefit_type IN ('capability','resource_scope','quota','limit_override','price_benefit','priority_access')),
      CHECK (status IN ('draft','active','retired'))
    );
    CREATE TABLE membership_plan_benefits (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      membership_plan_version_id UUID NOT NULL REFERENCES membership_plan_versions(id) ON DELETE CASCADE,
      benefit_definition_id UUID NOT NULL REFERENCES membership_benefit_definitions(id),
      benefit_value JSONB NOT NULL,
      valid_from_offset_days INTEGER,
      valid_until_offset_days INTEGER,
      sort_order INTEGER NOT NULL DEFAULT 0,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(membership_plan_version_id, benefit_definition_id),
      CHECK (valid_from_offset_days IS NULL OR valid_from_offset_days >= 0),
      CHECK (valid_until_offset_days IS NULL OR valid_until_offset_days >= 0)
    );
    CREATE INDEX ix_membership_benefits_code ON membership_benefit_definitions(benefit_code, status);
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE membership_plan_benefits;
    DROP TABLE membership_benefit_definitions;
    """)
