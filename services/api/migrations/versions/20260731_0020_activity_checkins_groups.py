"""Create activity check-in and grouping tables.

Revision ID: 20260731_0020
Revises: 20260731_0019
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260731_0020"
down_revision: str | None = "20260731_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _run(sql: str) -> None:
    for statement in sql.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(
        """
        CREATE TABLE activity_checkin_credentials (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          registration_id UUID NOT NULL UNIQUE REFERENCES activity_registrations(id),
          public_reference VARCHAR(64) NOT NULL UNIQUE,
          credential_secret_hash VARCHAR(128) NOT NULL,
          valid_from TIMESTAMPTZ NOT NULL,
          valid_until TIMESTAMPTZ NOT NULL,
          status VARCHAR(32) NOT NULL DEFAULT 'active',
          rotated_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (valid_until > valid_from)
        );
        CREATE TABLE activity_checkin_events (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          activity_id UUID NOT NULL REFERENCES activities(id),
          session_id UUID REFERENCES activity_sessions(id),
          registration_id UUID NOT NULL REFERENCES activity_registrations(id),
          action VARCHAR(32) NOT NULL,
          method VARCHAR(32) NOT NULL,
          performed_by UUID NOT NULL REFERENCES users(id),
          reason TEXT,
          device_reference VARCHAR(128),
          request_id UUID,
          occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_activity_checkin_registration_time
          ON activity_checkin_events(registration_id, occurred_at);
        CREATE TABLE activity_grouping_plans (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          activity_id UUID NOT NULL REFERENCES activities(id),
          plan_name VARCHAR(200) NOT NULL,
          grouping_method VARCHAR(32) NOT NULL,
          target_group_size INTEGER,
          target_group_count INTEGER,
          rule_schema_version INTEGER,
          grouping_rules JSONB NOT NULL DEFAULT '{}'::jsonb,
          random_seed VARCHAR(128),
          status VARCHAR(32) NOT NULL DEFAULT 'draft',
          created_by UUID NOT NULL REFERENCES users(id),
          locked_by UUID REFERENCES users(id),
          locked_at TIMESTAMPTZ,
          version INTEGER NOT NULL DEFAULT 1,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE activity_groups (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          grouping_plan_id UUID NOT NULL REFERENCES activity_grouping_plans(id) ON DELETE CASCADE,
          group_code VARCHAR(64) NOT NULL,
          display_name VARCHAR(200),
          facilitator_user_id UUID REFERENCES users(id),
          capacity INTEGER,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(grouping_plan_id, group_code)
        );
        CREATE TABLE activity_group_members (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          grouping_plan_id UUID NOT NULL REFERENCES activity_grouping_plans(id),
          group_id UUID NOT NULL REFERENCES activity_groups(id),
          registration_id UUID NOT NULL REFERENCES activity_registrations(id),
          assignment_source VARCHAR(32) NOT NULL,
          assignment_reason TEXT,
          assigned_by UUID REFERENCES users(id),
          assigned_at TIMESTAMPTZ NOT NULL,
          removed_at TIMESTAMPTZ,
          removed_by UUID REFERENCES users(id),
          removal_reason TEXT
        );
        CREATE UNIQUE INDEX uq_activity_group_member_active
          ON activity_group_members(grouping_plan_id, registration_id)
          WHERE removed_at IS NULL;
        """
    )


def downgrade() -> None:
    _run(
        """
        DROP TABLE activity_group_members;
        DROP TABLE activity_groups;
        DROP TABLE activity_grouping_plans;
        DROP TABLE activity_checkin_events;
        DROP TABLE activity_checkin_credentials;
        """
    )
