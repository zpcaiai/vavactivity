"""Create promotions and coupons.

Revision ID: 20260731_0014
Revises: 20260731_0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260731_0014"
down_revision: str | None = "20260731_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "promotions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("promotion_code", sa.String(128), nullable=False),
        sa.Column("internal_name", sa.String(200), nullable=False),
        sa.Column("promotion_type", sa.String(32), nullable=False),
        sa.Column("application_mode", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), server_default="draft", nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("stackability", sa.String(32), server_default="exclusive", nullable=False),
        sa.Column("rules", postgresql.JSONB(), nullable=False),
        sa.Column("benefits", postgresql.JSONB(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("total_redemption_limit", sa.Integer()),
        sa.Column("per_user_redemption_limit", sa.Integer()),
        sa.Column("budget_limit_minor", sa.BigInteger()),
        sa.Column("budget_currency", sa.String(3)),
        sa.Column("current_redemption_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "current_discount_total_minor", sa.BigInteger(), server_default="0", nullable=False
        ),
        sa.Column(
            "created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from", name="ck_promotions_window"
        ),
        sa.CheckConstraint(
            "total_redemption_limit IS NULL OR total_redemption_limit > 0",
            name="ck_promotions_total_limit",
        ),
        sa.CheckConstraint(
            "per_user_redemption_limit IS NULL OR per_user_redemption_limit > 0",
            name="ck_promotions_user_limit",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("promotion_code"),
    )
    op.create_table(
        "coupons",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "promotion_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("promotions.id"),
            nullable=False,
        ),
        sa.Column("coupon_code_normalized", sa.String(128), nullable=False),
        sa.Column("display_code", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), server_default="active", nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("total_redemption_limit", sa.Integer()),
        sa.Column("per_user_redemption_limit", sa.Integer()),
        sa.Column("current_redemption_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("assigned_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from",
            name="ck_coupons_window",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("coupon_code_normalized"),
    )


def downgrade() -> None:
    op.drop_table("coupons")
    op.drop_table("promotions")
