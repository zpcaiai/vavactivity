"""Add immutable execution schemas to registered Skill versions.

Revision ID: 20260806_0085
Revises: 20260806_0084

Module: skills_platform
Risk: low
Estimated lock: under 5 seconds
Backfill: existing versions remain non-executable until schemas are attached
Rollback: allowed before schema-backed executions are created
"""

from alembic import op

revision = "20260806_0085"
down_revision = "20260806_0084"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE registered_skill_versions
          ADD COLUMN input_schema JSONB,
          ADD COLUMN output_schema JSONB,
          ADD COLUMN error_schema JSONB
        """
    )
    op.execute(
        """
        ALTER TABLE registered_skill_versions
          ADD CONSTRAINT ck_skill_version_input_schema_object
            CHECK (input_schema IS NULL OR jsonb_typeof(input_schema)='object'),
          ADD CONSTRAINT ck_skill_version_output_schema_object
            CHECK (output_schema IS NULL OR jsonb_typeof(output_schema)='object'),
          ADD CONSTRAINT ck_skill_version_error_schema_object
            CHECK (error_schema IS NULL OR jsonb_typeof(error_schema)='object')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE registered_skill_versions
          DROP CONSTRAINT ck_skill_version_error_schema_object,
          DROP CONSTRAINT ck_skill_version_output_schema_object,
          DROP CONSTRAINT ck_skill_version_input_schema_object,
          DROP COLUMN error_schema,
          DROP COLUMN output_schema,
          DROP COLUMN input_schema;
        """
    )
