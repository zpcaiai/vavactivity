"""Create activity waitlists.

Revision ID: 20260731_0019
Revises: 20260731_0018
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260731_0019"
down_revision: str | None = "20260731_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE activity_waitlist_entries (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          activity_id UUID NOT NULL REFERENCES activities(id),
          ticket_type_id UUID NOT NULL REFERENCES activity_ticket_types(id),
          user_id UUID NOT NULL REFERENCES users(id),
          registration_id UUID NOT NULL REFERENCES activity_registrations(id),
          status VARCHAR(32) NOT NULL,
          sequence_number BIGINT NOT NULL,
          priority_score INTEGER NOT NULL DEFAULT 0,
          joined_at TIMESTAMPTZ NOT NULL,
          promotion_offered_at TIMESTAMPTZ,
          promotion_offer_expires_at TIMESTAMPTZ,
          promoted_at TIMESTAMPTZ,
          manual_order_override INTEGER,
          override_reason TEXT,
          overridden_by UUID REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(activity_id, ticket_type_id, user_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_activity_waitlist_order
          ON activity_waitlist_entries(
            activity_id, ticket_type_id, status, priority_score DESC,
            manual_order_override ASC, sequence_number ASC
          )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE activity_waitlist_entries")
