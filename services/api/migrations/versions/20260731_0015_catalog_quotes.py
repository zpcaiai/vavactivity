"""Create pricing quotes and reservation records.

Revision ID: 20260731_0015
Revises: 20260731_0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260731_0015"
down_revision: str | None = "20260731_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pricing_quotes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("anonymous_session_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "sku_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_skus.id"),
            nullable=False,
        ),
        sa.Column(
            "price_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prices.id"),
            nullable=False,
        ),
        sa.Column(
            "price_book_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("price_books.id"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False),
        sa.Column("unit_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("subtotal_minor", sa.BigInteger(), nullable=False),
        sa.Column("discount_total_minor", sa.BigInteger(), nullable=False),
        sa.Column("tax_estimate_minor", sa.BigInteger()),
        sa.Column("total_minor", sa.BigInteger(), nullable=False),
        sa.Column("calculation_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("quantity > 0", name="ck_quotes_quantity_positive"),
        sa.CheckConstraint(
            "unit_amount_minor >= 0 AND subtotal_minor >= 0 "
            "AND discount_total_minor >= 0 AND total_minor >= 0",
            name="ck_quotes_amounts_nonnegative",
        ),
        sa.CheckConstraint(
            "(user_id IS NOT NULL) <> (anonymous_session_id IS NOT NULL)",
            name="ck_quotes_principal",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "inventory_reservations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "inventory_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inventory_items.id"),
            nullable=False,
        ),
        sa.Column(
            "sku_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_skus.id"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("anonymous_session_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "pricing_quote_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pricing_quotes.id"),
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("release_reason", sa.String(128)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("quantity > 0", name="ck_reservations_quantity_positive"),
        sa.CheckConstraint(
            "(user_id IS NOT NULL) OR (anonymous_session_id IS NOT NULL)",
            name="ck_reservations_principal",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_inventory_reservations_expiry",
        "inventory_reservations",
        ["status", "expires_at"],
    )
    op.create_table(
        "coupon_redemption_reservations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("coupon_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("coupons.id")),
        sa.Column(
            "promotion_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("promotions.id"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column(
            "pricing_quote_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pricing_quotes.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reserved_discount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("reserved_discount_minor >= 0", name="ck_coupon_reservation_amount"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("coupon_redemption_reservations")
    op.drop_index("ix_inventory_reservations_expiry", table_name="inventory_reservations")
    op.drop_table("inventory_reservations")
    op.drop_table("pricing_quotes")
