"""Create catalog inventory and movement ledger.

Revision ID: 20260731_0013
Revises: 20260731_0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260731_0013"
down_revision: str | None = "20260731_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inventory_items",
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
        sa.Column("inventory_policy", sa.String(32), nullable=False),
        sa.Column("total_capacity", sa.Integer()),
        sa.Column("reserved_quantity", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sold_quantity", sa.Integer(), server_default="0", nullable=False),
        sa.Column("safety_stock", sa.Integer(), server_default="0", nullable=False),
        sa.Column("overselling_allowed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("oversell_limit", sa.Integer(), server_default="0", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "reserved_quantity >= 0 AND sold_quantity >= 0 AND safety_stock >= 0 "
            "AND oversell_limit >= 0",
            name="ck_inventory_quantities_nonnegative",
        ),
        sa.CheckConstraint(
            "(inventory_policy = 'unlimited' AND total_capacity IS NULL) OR "
            "(inventory_policy <> 'unlimited' AND total_capacity IS NOT NULL "
            "AND total_capacity >= 0)",
            name="ck_inventory_capacity_policy",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sku_id"),
    )
    op.create_table(
        "inventory_movements",
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
        sa.Column("movement_type", sa.String(32), nullable=False),
        sa.Column("quantity_delta", sa.Integer(), nullable=False),
        sa.Column("before_quantity", sa.Integer(), nullable=False),
        sa.Column("after_quantity", sa.Integer(), nullable=False),
        sa.Column("reference_type", sa.String(64)),
        sa.Column("reference_id", postgresql.UUID(as_uuid=True)),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("request_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_inventory_movements_item_created",
        "inventory_movements",
        ["inventory_item_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_inventory_movements_item_created", table_name="inventory_movements")
    op.drop_table("inventory_movements")
    op.drop_table("inventory_items")
