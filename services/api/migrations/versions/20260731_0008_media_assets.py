"""Create media library.

Revision ID: 20260731_0008
Revises: 20260731_0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260731_0008"
down_revision: str | None = "20260731_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_assets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("storage_provider", sa.String(32), nullable=False),
        sa.Column("bucket_name", sa.String(128), nullable=False),
        sa.Column("object_key", sa.String(500), nullable=False),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("media_type", sa.String(64), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("duration_seconds", sa.Numeric(12, 3)),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column("visibility", sa.String(32), server_default="private", nullable=False),
        sa.Column("processing_status", sa.String(32), nullable=False),
        sa.Column(
            "uploaded_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
    )
    op.create_table(
        "media_asset_localizations",
        sa.Column(
            "media_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_assets.id"),
            nullable=False,
        ),
        sa.Column("locale", sa.String(16), nullable=False),
        sa.Column("alt_text", sa.String(500)),
        sa.Column("caption", sa.Text()),
        sa.Column("accessibility_description", sa.Text()),
        sa.PrimaryKeyConstraint("media_id", "locale"),
    )
    op.create_foreign_key(
        "fk_content_localization_cover_media",
        "content_localizations",
        "media_assets",
        ["cover_media_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_content_localization_cover_media", "content_localizations", type_="foreignkey"
    )
    op.drop_table("media_asset_localizations")
    op.drop_table("media_assets")
