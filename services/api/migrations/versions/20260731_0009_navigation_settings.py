"""Create navigation and site settings.

Revision ID: 20260731_0009
Revises: 20260731_0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260731_0009"
down_revision: str | None = "20260731_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "navigation_menus",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "navigation_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "menu_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("navigation_menus.id"),
            nullable=False,
        ),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("navigation_items.id")),
        sa.Column("internal_name", sa.String(128), nullable=False),
        sa.Column("link_type", sa.String(32), nullable=False),
        sa.Column("target_entry_id", postgresql.UUID(as_uuid=True)),
        sa.Column("external_url", sa.Text()),
        sa.Column("route_name", sa.String(128)),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("open_in_new_tab", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("required_auth", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "navigation_item_localizations",
        sa.Column(
            "navigation_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("navigation_items.id"),
            nullable=False,
        ),
        sa.Column("locale", sa.String(16), nullable=False),
        sa.Column("label", sa.String(160), nullable=False),
        sa.PrimaryKeyConstraint("navigation_item_id", "locale"),
    )
    op.create_table(
        "site_settings",
        sa.Column("setting_key", sa.String(160), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("value_type", sa.String(32), nullable=False),
        sa.Column("is_public", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("setting_key"),
    )


def downgrade() -> None:
    op.drop_table("site_settings")
    op.drop_table("navigation_item_localizations")
    op.drop_table("navigation_items")
    op.drop_table("navigation_menus")
