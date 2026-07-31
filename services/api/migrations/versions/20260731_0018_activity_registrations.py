"""Create activity registrations and projection inbox.

Revision ID: 20260731_0018
Revises: 20260731_0017
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260731_0018"
down_revision: str | None = "20260731_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _run(sql: str) -> None:
    for statement in sql.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(
        """
        CREATE TABLE activity_registrations (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          registration_number VARCHAR(64) NOT NULL UNIQUE,
          activity_id UUID NOT NULL REFERENCES activities(id),
          ticket_type_id UUID NOT NULL REFERENCES activity_ticket_types(id),
          user_id UUID NOT NULL REFERENCES users(id),
          status VARCHAR(32) NOT NULL,
          attendance_status VARCHAR(32) NOT NULL DEFAULT 'not_checked_in',
          form_schema_version INTEGER NOT NULL,
          form_response_encrypted TEXT NOT NULL,
          pricing_quote_id UUID REFERENCES pricing_quotes(id),
          order_id UUID REFERENCES orders(id),
          entitlement_id UUID REFERENCES entitlements(id),
          review_status VARCHAR(32),
          reviewed_by UUID REFERENCES users(id),
          reviewed_at TIMESTAMPTZ,
          review_reason_code VARCHAR(128),
          user_visible_review_message VARCHAR(500),
          review_notes_encrypted TEXT,
          confirmed_at TIMESTAMPTZ,
          cancelled_at TIMESTAMPTZ,
          version INTEGER NOT NULL DEFAULT 1,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(activity_id, user_id)
        );
        CREATE TABLE activity_registration_history (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          registration_id UUID NOT NULL REFERENCES activity_registrations(id) ON DELETE CASCADE,
          from_status VARCHAR(32),
          to_status VARCHAR(32) NOT NULL,
          reason_code VARCHAR(128),
          reason TEXT,
          actor_type VARCHAR(32) NOT NULL,
          actor_user_id UUID,
          request_id UUID,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_activity_registration_history_created
          ON activity_registration_history(registration_id, created_at);
        CREATE TABLE activity_inbox_events (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          source_event_id UUID NOT NULL UNIQUE,
          event_type VARCHAR(128) NOT NULL,
          processing_status VARCHAR(32) NOT NULL,
          received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          processed_at TIMESTAMPTZ
        );
        """
    )


def downgrade() -> None:
    _run(
        """
        DROP TABLE activity_inbox_events;
        DROP TABLE activity_registration_history;
        DROP TABLE activity_registrations;
        """
    )
