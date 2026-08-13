# ruff: noqa: E501

"""Profile media assets, MBTI/intro profile, completeness and share consent.

Covers PROFILE-001.

Revision ID: 20260812_0099
Revises: 20260812_0098
"""

import re

from alembic import op

revision = "20260812_0099"
down_revision = "20260812_0098"
branch_labels = None
depends_on = None


def _split_statements(script: str) -> list[str]:
    """Split a SQL script on statement boundaries.

    A naive ``script.split(";")`` breaks on any semicolon, including ones
    inside a ``--`` comment or a string literal — which silently turns the
    remainder of a comment into a bogus statement. Postgres then fails on
    something like ``syntax error at or near "it"``, pointing at a line that
    looks perfectly fine.

    This walks the script instead, skipping over line comments, block
    comments, single-quoted strings and dollar-quoted bodies.
    """

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
        -- PROFILE-001. access_token is the only public handle for private media:
        -- an HMAC of the asset id under a server secret, so a private photo is
        -- not reachable by guessing an id or a sequence number.
        --
        -- moderation_state defaults to 'pending': nothing becomes publishable
        -- merely because it finished uploading.
        CREATE TABLE profile_media_assets (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          owner_id UUID NOT NULL REFERENCES users(id),
          kind VARCHAR(8) NOT NULL,
          state VARCHAR(16) NOT NULL DEFAULT 'uploading',
          moderation_state VARCHAR(16) NOT NULL DEFAULT 'pending',
          position INTEGER NOT NULL DEFAULT 1,
          mime_type VARCHAR(128) NOT NULL,
          byte_size BIGINT NOT NULL DEFAULT 0,
          duration_seconds NUMERIC(8,2),
          access_token VARCHAR(64) NOT NULL,
          replaces_asset_id UUID,
          rejection_reason_code VARCHAR(64),
          moderated_by UUID REFERENCES users(id),
          moderated_at TIMESTAMPTZ,
          deleted_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (kind IN ('photo','video')),
          CHECK (state IN ('uploading','active','replaced','deleted')),
          CHECK (moderation_state IN ('pending','approved','rejected','withdrawn')),
          CHECK (position >= 1 AND position <= 3),
          CHECK (byte_size >= 0),
          -- Phase-one video limits, restated in the database so a bad service
          -- deploy cannot store a ten-minute "short video".
          CHECK (kind <> 'video' OR state = 'uploading' OR (duration_seconds IS NOT NULL AND duration_seconds >= 3 AND duration_seconds <= 30)),
          CHECK (kind <> 'photo' OR duration_seconds IS NULL),
          CHECK (moderation_state <> 'rejected' OR rejection_reason_code IS NOT NULL),
          CHECK (state <> 'deleted' OR deleted_at IS NOT NULL)
        );
        CREATE UNIQUE INDEX profile_media_assets_token_key
          ON profile_media_assets (access_token) WHERE access_token <> '';
        CREATE INDEX profile_media_assets_owner_idx
          ON profile_media_assets (owner_id, kind, state);
        CREATE INDEX profile_media_assets_moderation_idx
          ON profile_media_assets (moderation_state, created_at) WHERE state = 'active';

        -- At most three active photos and exactly one active video per member.
        -- Partial unique indexes make the phase-one limits a database fact, not
        -- just a service-layer check (PROFILE-001).
        CREATE UNIQUE INDEX profile_media_assets_photo_slot_key
          ON profile_media_assets (owner_id, position)
          WHERE state = 'active' AND kind = 'photo';
        CREATE UNIQUE INDEX profile_media_assets_single_video_key
          ON profile_media_assets (owner_id)
          WHERE state = 'active' AND kind = 'video';

        CREATE TABLE profile_media_profiles (
          user_id UUID PRIMARY KEY REFERENCES users(id),
          mbti VARCHAR(4),
          intro_encrypted TEXT,
          city_code VARCHAR(32),
          is_published BOOLEAN NOT NULL DEFAULT false,
          completeness_percent INTEGER NOT NULL DEFAULT 0,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (completeness_percent >= 0 AND completeness_percent <= 100),
          CHECK (mbti IS NULL OR mbti IN (
            'ISTJ','ISFJ','INFJ','INTJ','ISTP','ISFP','INFP','INTP',
            'ESTP','ESFP','ENFP','ENTP','ESTJ','ESFJ','ENFJ','ENTJ'))
        );

        -- PROFILE-001. Every flag defaults to false: the share card is empty
        -- until the member opts each field in, and share_enabled gates all of
        -- them so one switch turns the whole card off.
        CREATE TABLE profile_share_consents (
          user_id UUID PRIMARY KEY REFERENCES users(id),
          share_enabled BOOLEAN NOT NULL DEFAULT false,
          share_photos BOOLEAN NOT NULL DEFAULT false,
          share_video BOOLEAN NOT NULL DEFAULT false,
          share_mbti BOOLEAN NOT NULL DEFAULT false,
          share_intro BOOLEAN NOT NULL DEFAULT false,
          share_city BOOLEAN NOT NULL DEFAULT false,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE profile_media_audits (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          asset_id UUID,
          owner_id UUID REFERENCES users(id),
          actor_id UUID REFERENCES users(id),
          actor_kind VARCHAR(16) NOT NULL,
          action VARCHAR(128) NOT NULL,
          reason TEXT,
          metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (actor_kind IN ('member','admin','system'))
        );
        CREATE INDEX profile_media_audits_asset_idx
          ON profile_media_audits (asset_id, created_at DESC);
        CREATE INDEX profile_media_audits_owner_idx
          ON profile_media_audits (owner_id, created_at DESC);
        """
    )

    # No backfill of profile_share_consents: an absent row already means "share
    # nothing", which is the safe default. Creating rows would only add noise.


def downgrade() -> None:
    _run(
        """
        DROP TABLE IF EXISTS profile_media_audits;
        DROP TABLE IF EXISTS profile_share_consents;
        DROP TABLE IF EXISTS profile_media_profiles;
        DROP TABLE IF EXISTS profile_media_assets;
        """
    )
