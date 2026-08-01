"""Add privacy inventories and classifications.

Revision ID: 20260801_0042
Revises: 20260801_0041
"""

# ruff: noqa: E501

from alembic import op

revision = "20260801_0042"
down_revision = "20260801_0041"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE privacy_data_assets (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), asset_code VARCHAR(128) NOT NULL UNIQUE,
      module_code VARCHAR(64) NOT NULL, storage_type VARCHAR(64) NOT NULL, entity_name VARCHAR(200) NOT NULL,
      field_path VARCHAR(500), data_category VARCHAR(64) NOT NULL, sensitivity VARCHAR(32) NOT NULL,
      processing_purposes JSONB NOT NULL, lawful_or_policy_basis JSONB NOT NULL DEFAULT '[]'::jsonb,
      export_supported BOOLEAN NOT NULL, correction_supported BOOLEAN NOT NULL, erasure_mode VARCHAR(32) NOT NULL,
      retention_policy_code VARCHAR(128), owner_team VARCHAR(128) NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_privacy_assets_module ON privacy_data_assets(module_code,data_category);
    CREATE TABLE privacy_processing_activities (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), activity_code VARCHAR(128) NOT NULL UNIQUE,
      name VARCHAR(300) NOT NULL, purpose TEXT NOT NULL, data_categories JSONB NOT NULL,
      data_subject_types JSONB NOT NULL, recipient_categories JSONB NOT NULL,
      external_processors JSONB NOT NULL DEFAULT '[]'::jsonb, retention_policy_codes JSONB NOT NULL,
      automated_decisioning BOOLEAN NOT NULL DEFAULT false, ai_involved BOOLEAN NOT NULL DEFAULT false,
      owner_team VARCHAR(128) NOT NULL, status VARCHAR(32) NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE privacy_field_classifications (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), asset_code VARCHAR(128) NOT NULL,
      field_path VARCHAR(500) NOT NULL, sensitivity VARCHAR(32) NOT NULL, data_category VARCHAR(64) NOT NULL,
      encryption_required BOOLEAN NOT NULL, masking_policy_code VARCHAR(128), access_policy_code VARCHAR(128) NOT NULL,
      log_policy VARCHAR(32) NOT NULL, export_policy VARCHAR(32) NOT NULL, erasure_mode VARCHAR(32) NOT NULL,
      approved_by UUID NOT NULL REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(asset_code,field_path)
    );
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE privacy_field_classifications;
    DROP TABLE privacy_processing_activities;
    DROP TABLE privacy_data_assets;
    """)
