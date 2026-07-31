"""Create localized content entries.

Revision ID: 20260731_0006
Revises: 20260731_0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260731_0006"
down_revision: str | None = "20260731_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "content_entries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("entry_type", sa.String(32), nullable=False),
        sa.Column("internal_name", sa.String(160), nullable=False),
        sa.Column("canonical_slug", sa.String(200), nullable=False),
        sa.Column("status", sa.String(32), server_default="draft", nullable=False),
        sa.Column("default_locale", sa.String(16), nullable=False),
        sa.Column("visibility", sa.String(32), server_default="public", nullable=False),
        sa.Column(
            "author_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("reviewer_id", postgresql.UUID(as_uuid=True)),
        sa.Column("published_by", postgresql.UUID(as_uuid=True)),
        sa.Column("scheduled_publish_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("current_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entry_type", "canonical_slug"),
    )
    op.create_table(
        "content_localizations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "entry_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("content_entries.id"),
            nullable=False,
        ),
        sa.Column("locale", sa.String(16), nullable=False),
        sa.Column("localized_slug", sa.String(200)),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("subtitle", sa.String(500)),
        sa.Column("excerpt", sa.Text()),
        sa.Column(
            "content_blocks",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("plain_text", sa.Text()),
        sa.Column("seo_title", sa.String(300)),
        sa.Column("seo_description", sa.String(500)),
        sa.Column("social_title", sa.String(300)),
        sa.Column("social_description", sa.String(500)),
        sa.Column("cover_media_id", postgresql.UUID(as_uuid=True)),
        sa.Column("translation_status", sa.String(32), server_default="draft", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entry_id", "locale"),
        sa.UniqueConstraint("locale", "localized_slug"),
    )
    op.create_table(
        "article_metadata",
        sa.Column(
            "entry_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("content_entries.id"),
            nullable=False,
        ),
        sa.Column("category", sa.String(128)),
        sa.Column("author_display_name", sa.String(160)),
        sa.Column("reading_time_minutes", sa.Integer()),
        sa.Column("featured", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("source_reference", sa.Text()),
        sa.Column("original_published_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("entry_id"),
    )
    op.create_table(
        "testimonial_metadata",
        sa.Column(
            "entry_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("content_entries.id"),
            nullable=False,
        ),
        sa.Column("subject_display_name", sa.String(160)),
        sa.Column("relationship_stage", sa.String(64)),
        sa.Column("consent_status", sa.String(32), nullable=False),
        sa.Column("consent_record_id", postgresql.UUID(as_uuid=True)),
        sa.Column("anonymity_level", sa.String(32), nullable=False),
        sa.Column("featured", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.PrimaryKeyConstraint("entry_id"),
    )


def downgrade() -> None:
    op.drop_table("testimonial_metadata")
    op.drop_table("article_metadata")
    op.drop_table("content_localizations")
    op.drop_table("content_entries")
