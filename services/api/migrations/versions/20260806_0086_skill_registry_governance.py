"""Add publisher ownership, independent review, and enforcement evidence.

Revision ID: 20260806_0086
Revises: 20260806_0085
"""

from alembic import op

revision = "20260806_0086"
down_revision = "20260806_0085"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(
        """
        ALTER TABLE skill_publishers ADD COLUMN created_by UUID REFERENCES users(id);

        CREATE TABLE skill_publisher_members (
          publisher_id UUID NOT NULL REFERENCES skill_publishers(id) ON DELETE CASCADE,
          user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          member_role VARCHAR(32) NOT NULL,
          status VARCHAR(32) NOT NULL DEFAULT 'active',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY (publisher_id,user_id),
          CHECK (member_role IN ('owner','developer','release_manager')),
          CHECK (status IN ('active','suspended','revoked'))
        );

        ALTER TABLE registered_skill_versions
          ADD COLUMN submitted_by UUID REFERENCES users(id),
          ADD COLUMN signature_key_id VARCHAR(255),
          ADD COLUMN security_reviewed_by UUID REFERENCES users(id),
          ADD COLUMN security_report JSONB,
          ADD COLUMN quarantined_at TIMESTAMPTZ,
          ADD COLUMN quarantine_reason_code VARCHAR(128);

        ALTER TABLE marketplace_appeals ADD COLUMN submitted_by UUID REFERENCES users(id);

        CREATE TABLE skill_security_incidents (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          skill_version_id UUID REFERENCES registered_skill_versions(id),
          listing_id UUID REFERENCES marketplace_listings(id),
          severity VARCHAR(16) NOT NULL,
          status VARCHAR(32) NOT NULL DEFAULT 'open',
          reason_code VARCHAR(128) NOT NULL,
          evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_by UUID NOT NULL REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          resolved_at TIMESTAMPTZ,
          CHECK (severity IN ('low','medium','high','critical')),
          CHECK (status IN ('open','investigating','contained','resolved'))
        );
        CREATE INDEX ix_skill_security_incidents_status_created
          ON skill_security_incidents(status,created_at DESC);
        """
    )


def downgrade() -> None:
    _run(
        """
        DROP TABLE skill_security_incidents;
        ALTER TABLE marketplace_appeals DROP COLUMN submitted_by;
        ALTER TABLE registered_skill_versions
          DROP COLUMN quarantine_reason_code,
          DROP COLUMN quarantined_at,
          DROP COLUMN security_report,
          DROP COLUMN security_reviewed_by,
          DROP COLUMN signature_key_id,
          DROP COLUMN submitted_by;
        DROP TABLE skill_publisher_members;
        ALTER TABLE skill_publishers DROP COLUMN created_by;
        """
    )
