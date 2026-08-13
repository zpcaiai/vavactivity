# ruff: noqa: E501

"""Bind private profile assets to verified immutable storage objects.

Pre-hardening active assets used ``profile-media/<token>`` directly for both
upload and read. Existing objects stay readable through that legacy key; new
uploads use a temporary ``uploads/`` key and are finalized into ``assets/``.
The deletion table is a durable retry queue, because changing a database state
to deleted is not the same thing as erasing private bytes from object storage.

Revision ID: 20260813_0112
Revises: 20260813_0111
"""

import re

from alembic import op

revision = "20260813_0112"
down_revision = "20260813_0111"
branch_labels = None
depends_on = None


def _split_statements(script: str) -> list[str]:
    """Split SQL without breaking comments, strings or dollar-quoted blocks."""

    statements: list[str] = []
    buffer: list[str] = []
    index = 0
    length = len(script)
    while index < length:
        char = script[index]
        pair = script[index : index + 2]
        if pair == "--":
            end = script.find("\n", index)
            index = length if end == -1 else end
            continue
        if pair == "/*":
            end = script.find("*/", index + 2)
            index = length if end == -1 else end + 2
            continue
        if char == "'":
            buffer.append(char)
            index += 1
            while index < length:
                buffer.append(script[index])
                if script[index] == "'":
                    if script[index : index + 2] == "''":
                        buffer.append(script[index + 1])
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        if char == "$":
            match = re.match(r"\$[A-Za-z_]*\$", script[index:])
            if match:
                tag = match.group(0)
                end = script.find(tag, index + len(tag))
                stop = length if end == -1 else end + len(tag)
                buffer.append(script[index:stop])
                index = stop
                continue
        if char == ";":
            statements.append("".join(buffer))
            buffer = []
            index += 1
            continue
        buffer.append(char)
        index += 1
    statements.append("".join(buffer))
    return [item.strip() for item in statements if item.strip()]


def _run(script: str) -> None:
    for statement in _split_statements(script):
        op.execute(statement)


def upgrade() -> None:
    _run(
        """
        ALTER TABLE profile_media_assets
          ADD COLUMN IF NOT EXISTS storage_key VARCHAR(512),
          ADD COLUMN IF NOT EXISTS storage_etag VARCHAR(255),
          ADD COLUMN IF NOT EXISTS storage_version_id VARCHAR(255),
          ADD COLUMN IF NOT EXISTS checksum_sha256 VARCHAR(64),
          ADD COLUMN IF NOT EXISTS storage_verified_at TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS upload_expires_at TIMESTAMPTZ;

        -- Preserve the exact pre-hardening key. The first successful grant HEAD
        -- verifies existence and records no new trust claim about MIME/content;
        -- these rows must be re-moderated operationally if content provenance is
        -- required. New finalizations always write under assets/ instead.
        UPDATE profile_media_assets
           SET storage_key = 'profile-media/' || access_token
         WHERE access_token <> '' AND storage_key IS NULL;

        -- Old abandoned uploading rows did not carry an expiry. Give them a
        -- finite grace window so the maintenance worker can reclaim both the row
        -- and any staged/legacy object rather than preserving them forever.
        UPDATE profile_media_assets
           SET upload_expires_at = now() + interval '20 minutes'
         WHERE state = 'uploading' AND upload_expires_at IS NULL;

        -- Expand-phase compatibility for a pre-0112 API binary. That binary
        -- inserts an uploading row with an empty token, then sets the token in
        -- a second statement, and never writes storage_key. Without this
        -- trigger its later uploading -> active transition violates the
        -- active_storage_key CHECK below. It would also create post-backfill
        -- rows that a new binary cannot resolve. New binaries always provide
        -- an explicit uploads/ or assets/ key, which this trigger preserves.
        CREATE OR REPLACE FUNCTION profile_media_bind_legacy_storage_key()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $profile_media_legacy_binding$
        BEGIN
          IF NEW.storage_key IS NULL AND COALESCE(NEW.access_token, '') <> '' THEN
            NEW.storage_key := 'profile-media/' || NEW.access_token;
          END IF;
          IF NEW.state = 'uploading' AND NEW.upload_expires_at IS NULL THEN
            NEW.upload_expires_at := now() + interval '20 minutes';
          END IF;
          RETURN NEW;
        END
        $profile_media_legacy_binding$;
        DROP TRIGGER IF EXISTS profile_media_bind_legacy_storage_key
          ON profile_media_assets;
        CREATE TRIGGER profile_media_bind_legacy_storage_key
          BEFORE INSERT OR UPDATE OF access_token, storage_key, state
          ON profile_media_assets
          FOR EACH ROW
          EXECUTE FUNCTION profile_media_bind_legacy_storage_key();

        ALTER TABLE profile_media_assets
          ADD CONSTRAINT profile_media_assets_active_storage_key
          CHECK (state <> 'active' OR storage_key IS NOT NULL);
        ALTER TABLE profile_media_assets
          ADD CONSTRAINT profile_media_assets_checksum_shape
          CHECK (checksum_sha256 IS NULL OR checksum_sha256 ~ '^[0-9a-f]{64}$');
        CREATE INDEX IF NOT EXISTS profile_media_assets_upload_expiry_idx
          ON profile_media_assets (upload_expires_at)
          WHERE state = 'uploading' AND storage_verified_at IS NULL;

        CREATE TABLE IF NOT EXISTS profile_media_storage_deletions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          asset_id UUID,
          owner_id UUID,
          access_token VARCHAR(64) NOT NULL,
          storage_key VARCHAR(512) NOT NULL UNIQUE,
          state VARCHAR(16) NOT NULL DEFAULT 'pending',
          attempts INTEGER NOT NULL DEFAULT 0,
          last_error TEXT,
          next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          completed_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (state IN ('pending','failed','completed')),
          CHECK (attempts >= 0),
          CHECK (state <> 'completed' OR completed_at IS NOT NULL)
        );
        ALTER TABLE profile_media_storage_deletions
          ADD COLUMN IF NOT EXISTS owner_id UUID;
        CREATE INDEX IF NOT EXISTS profile_media_storage_deletions_due_idx
          ON profile_media_storage_deletions (next_attempt_at, created_at)
          WHERE state = 'pending';
        CREATE INDEX IF NOT EXISTS profile_media_storage_deletions_owner_state_idx
          ON profile_media_storage_deletions (owner_id, state)
          WHERE owner_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    # Completed or pending physical-erasure work remains meaningful even when
    # application code rolls back. Dropping it would silently lose deletion
    # obligations, so the queue and populated integrity fields are retained.
    _run(
        """
        DROP INDEX IF EXISTS profile_media_assets_upload_expiry_idx;
        DROP TRIGGER IF EXISTS profile_media_bind_legacy_storage_key
          ON profile_media_assets;
        DROP FUNCTION IF EXISTS profile_media_bind_legacy_storage_key();
        ALTER TABLE profile_media_assets
          DROP CONSTRAINT IF EXISTS profile_media_assets_checksum_shape,
          DROP CONSTRAINT IF EXISTS profile_media_assets_active_storage_key;
        """
    )
