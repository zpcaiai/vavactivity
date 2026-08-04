"""Add private dating-profile photos and short-lived view tokens.

Revision ID: 20260804_0050
Revises: 20260804_0049
"""

# ruff: noqa: E501

from alembic import op

revision = "20260804_0050"
down_revision = "20260804_0049"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE dating_profile_photos (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      dating_profile_id UUID NOT NULL REFERENCES dating_profiles(id) ON DELETE CASCADE,
      media_asset_id UUID NOT NULL REFERENCES media_assets(id),
      derived_media_asset_id UUID REFERENCES media_assets(id),
      photo_role VARCHAR(32) NOT NULL,
      status VARCHAR(32) NOT NULL,
      visibility VARCHAR(64) NOT NULL DEFAULT 'verified_members',
      sort_order INTEGER NOT NULL DEFAULT 0,
      content_checksum_sha256 VARCHAR(64) NOT NULL,
      processing_report JSONB,
      moderation_report_encrypted TEXT,
      reviewed_by UUID REFERENCES users(id),
      reviewed_at TIMESTAMPTZ,
      rejection_reason_code VARCHAR(128),
      rejection_message_safe TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      deleted_at TIMESTAMPTZ
    );
    CREATE UNIQUE INDEX uq_dating_profile_primary_photo ON dating_profile_photos(dating_profile_id)
      WHERE photo_role='primary' AND deleted_at IS NULL AND status <> 'deleted';
    CREATE INDEX ix_dating_profile_photos_profile ON dating_profile_photos(dating_profile_id, sort_order)
      WHERE deleted_at IS NULL;
    CREATE INDEX ix_dating_profile_photos_review ON dating_profile_photos(status, created_at)
      WHERE status='review_required';
    CREATE TABLE dating_profile_photo_view_tokens (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      photo_id UUID NOT NULL REFERENCES dating_profile_photos(id) ON DELETE CASCADE,
      viewer_user_id UUID NOT NULL REFERENCES users(id),
      token_hash VARCHAR(128) NOT NULL UNIQUE,
      view_context VARCHAR(64) NOT NULL,
      expires_at TIMESTAMPTZ NOT NULL,
      revoked_at TIMESTAMPTZ,
      consumed_at TIMESTAMPTZ,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_dating_photo_view_tokens_photo ON dating_profile_photo_view_tokens(photo_id, expires_at DESC);
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE dating_profile_photo_view_tokens;
    DROP TABLE dating_profile_photos;
    """)
