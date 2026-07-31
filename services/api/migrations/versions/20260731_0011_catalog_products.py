"""Create catalog categories, products and SKUs.

Revision ID: 20260731_0011
Revises: 20260731_0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260731_0011"
down_revision: str | None = "20260731_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_categories",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "parent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_categories.id"),
        ),
        sa.Column("category_code", sa.String(128), nullable=False),
        sa.Column("internal_name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(32), server_default="active", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("category_code"),
    )
    op.create_table(
        "product_category_localizations",
        sa.Column(
            "category_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_categories.id"),
            nullable=False,
        ),
        sa.Column("locale", sa.String(16), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(500)),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.PrimaryKeyConstraint("category_id", "locale"),
        sa.UniqueConstraint("locale", "slug"),
    )
    op.create_table(
        "products",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("product_code", sa.String(128), nullable=False),
        sa.Column("product_type", sa.String(64), nullable=False),
        sa.Column("fulfillment_type", sa.String(64), nullable=False),
        sa.Column("internal_name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(32), server_default="draft", nullable=False),
        sa.Column("visibility", sa.String(32), server_default="public", nullable=False),
        sa.Column("default_locale", sa.String(16), nullable=False),
        sa.Column(
            "category_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_categories.id"),
        ),
        sa.Column("purchasable_from", sa.DateTime(timezone=True)),
        sa.Column("purchasable_until", sa.DateTime(timezone=True)),
        sa.Column("featured", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "purchasable_until IS NULL OR purchasable_from IS NULL "
            "OR purchasable_until > purchasable_from",
            name="ck_products_purchase_window",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_code"),
    )
    op.create_table(
        "product_localizations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id"),
            nullable=False,
        ),
        sa.Column("locale", sa.String(16), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("short_description", sa.String(500)),
        sa.Column(
            "description_blocks",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("seo_title", sa.String(300)),
        sa.Column("seo_description", sa.String(500)),
        sa.Column(
            "cover_media_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_assets.id"),
        ),
        sa.Column("translation_status", sa.String(32), server_default="draft", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", "locale"),
        sa.UniqueConstraint("locale", "slug"),
    )
    op.create_table(
        "product_skus",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id"),
            nullable=False,
        ),
        sa.Column("sku_code", sa.String(128), nullable=False),
        sa.Column("internal_name", sa.String(200), nullable=False),
        sa.Column("billing_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), server_default="draft", nullable=False),
        sa.Column("service_quantity", sa.Integer()),
        sa.Column("service_unit", sa.String(64)),
        sa.Column(
            "entitlement_definition",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "fulfillment_configuration",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("inventory_policy", sa.String(32), nullable=False),
        sa.Column("purchase_limit_per_user", sa.Integer()),
        sa.Column("purchase_limit_total", sa.Integer()),
        sa.Column("purchasable_from", sa.DateTime(timezone=True)),
        sa.Column("purchasable_until", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "service_quantity IS NULL OR service_quantity > 0",
            name="ck_skus_service_quantity_positive",
        ),
        sa.CheckConstraint(
            "purchase_limit_per_user IS NULL OR purchase_limit_per_user > 0",
            name="ck_skus_user_limit_positive",
        ),
        sa.CheckConstraint(
            "purchase_limit_total IS NULL OR purchase_limit_total > 0",
            name="ck_skus_total_limit_positive",
        ),
        sa.CheckConstraint(
            "purchasable_until IS NULL OR purchasable_from IS NULL "
            "OR purchasable_until > purchasable_from",
            name="ck_skus_purchase_window",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sku_code"),
    )


def downgrade() -> None:
    op.drop_table("product_skus")
    op.drop_table("product_localizations")
    op.drop_table("products")
    op.drop_table("product_category_localizations")
    op.drop_table("product_categories")
