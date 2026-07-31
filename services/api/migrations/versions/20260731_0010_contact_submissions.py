"""Create privacy-aware contact submissions.

Revision ID: 20260731_0010
Revises: 20260731_0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260731_0010"
down_revision: str | None = "20260731_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "contact_submissions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("submission_type", sa.String(64), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("region", sa.String(128)),
        sa.Column("subject", sa.String(300)),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("locale", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), server_default="new", nullable=False),
        sa.Column("assigned_to", postgresql.UUID(as_uuid=True)),
        sa.Column("privacy_consent_version", sa.String(32), nullable=False),
        sa.Column("privacy_consented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_page", sa.String(300)),
        sa.Column("ip_address_hash", sa.String(128)),
        sa.Column("user_agent_hash", sa.String(128)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("contact_submissions")
