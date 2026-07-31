"""Create catalog currencies and immutable prices.

Revision ID: 20260731_0012
Revises: 20260731_0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260731_0012"
down_revision: str | None = "20260731_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "supported_currencies",
        sa.Column("currency_code", sa.String(3), nullable=False),
        sa.Column("exponent", sa.SmallInteger(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("exponent >= 0 AND exponent <= 4", name="ck_currency_exponent"),
        sa.PrimaryKeyConstraint("currency_code"),
    )
    op.create_table(
        "price_books",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("price_book_code", sa.String(128), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("region_code", sa.String(64)),
        sa.Column("customer_segment", sa.String(64)),
        sa.Column("status", sa.String(32), server_default="draft", nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from",
            name="ck_price_books_window",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("price_book_code"),
    )
    op.create_table(
        "prices",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "sku_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_skus.id"),
            nullable=False,
        ),
        sa.Column(
            "price_book_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("price_books.id"),
            nullable=False,
        ),
        sa.Column(
            "currency_code",
            sa.String(3),
            sa.ForeignKey("supported_currencies.currency_code"),
            nullable=False,
        ),
        sa.Column("unit_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("compare_at_amount_minor", sa.BigInteger()),
        sa.Column("billing_type", sa.String(32), nullable=False),
        sa.Column("billing_interval", sa.String(32)),
        sa.Column("billing_interval_count", sa.Integer()),
        sa.Column("tax_behavior", sa.String(32), server_default="unspecified", nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(32), server_default="draft", nullable=False),
        sa.Column(
            "external_price_references",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "supersedes_price_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prices.id"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("unit_amount_minor >= 0", name="ck_prices_amount_nonnegative"),
        sa.CheckConstraint(
            "compare_at_amount_minor IS NULL OR compare_at_amount_minor >= unit_amount_minor",
            name="ck_prices_compare_at",
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from", name="ck_prices_window"
        ),
        sa.CheckConstraint(
            "(billing_type = 'recurring' AND billing_interval IS NOT NULL "
            "AND billing_interval_count > 0) OR "
            "(billing_type <> 'recurring' AND billing_interval IS NULL "
            "AND billing_interval_count IS NULL)",
            name="ck_prices_billing_interval",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_prices_resolution",
        "prices",
        ["sku_id", "currency_code", "status", "valid_from"],
    )
    op.create_table(
        "exchange_rate_snapshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("base_currency", sa.String(3), nullable=False),
        sa.Column("quote_currency", sa.String(3), nullable=False),
        sa.Column("rate_scaled", sa.BigInteger(), nullable=False),
        sa.Column("scale", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(128), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("rate_scaled > 0", name="ck_exchange_rate_positive"),
        sa.CheckConstraint("scale > 0", name="ck_exchange_rate_scale_positive"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("exchange_rate_snapshots")
    op.drop_index("ix_prices_resolution", table_name="prices")
    op.drop_table("prices")
    op.drop_table("price_books")
    op.drop_table("supported_currencies")
