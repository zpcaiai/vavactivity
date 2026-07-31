"""Create course video, enrollment and learning progress tables.

Revision ID: 20260731_0024
Revises: 20260731_0023
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260731_0024"
down_revision: str | None = "20260731_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _run(sql: str) -> None:
    for statement in sql.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(
        """
        CREATE TABLE course_video_assets (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          provider VARCHAR(64) NOT NULL,
          provider_environment VARCHAR(16) NOT NULL,
          media_asset_id UUID REFERENCES media_assets(id),
          provider_video_id VARCHAR(255),
          private_reference_encrypted TEXT,
          processing_status VARCHAR(32) NOT NULL,
          duration_seconds INTEGER CHECK (duration_seconds IS NULL OR duration_seconds > 0),
          width INTEGER,
          height INTEGER,
          playback_format VARCHAR(32),
          drm_policy VARCHAR(32) NOT NULL DEFAULT 'none',
          original_source_visibility VARCHAR(32) NOT NULL DEFAULT 'private',
          created_by UUID NOT NULL REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (original_source_visibility = 'private')
        );
        CREATE TABLE lesson_video_resources (
          lesson_id UUID PRIMARY KEY REFERENCES course_lessons(id) ON DELETE CASCADE,
          video_asset_id UUID NOT NULL REFERENCES course_video_assets(id),
          required_watch_basis_points INTEGER NOT NULL DEFAULT 9000
            CHECK (required_watch_basis_points BETWEEN 1 AND 10000),
          allow_seek BOOLEAN NOT NULL DEFAULT TRUE,
          allow_playback_speed BOOLEAN NOT NULL DEFAULT TRUE,
          captions_required BOOLEAN NOT NULL DEFAULT FALSE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE course_enrollments (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id UUID NOT NULL REFERENCES users(id),
          course_id UUID NOT NULL REFERENCES courses(id),
          course_version_id UUID NOT NULL REFERENCES course_versions(id),
          entitlement_id UUID REFERENCES entitlements(id),
          source_type VARCHAR(32) NOT NULL,
          source_reference_id UUID,
          status VARCHAR(32) NOT NULL,
          access_starts_at TIMESTAMPTZ,
          access_expires_at TIMESTAMPTZ,
          enrolled_at TIMESTAMPTZ NOT NULL,
          first_accessed_at TIMESTAMPTZ,
          completed_at TIMESTAMPTZ,
          suspended_at TIMESTAMPTZ,
          revoked_at TIMESTAMPTZ,
          version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (access_starts_at IS NULL OR access_expires_at IS NULL
                 OR access_expires_at > access_starts_at)
        );
        CREATE UNIQUE INDEX uq_course_enrollment_entitlement
          ON course_enrollments(user_id, course_id, entitlement_id)
          WHERE entitlement_id IS NOT NULL;
        CREATE UNIQUE INDEX uq_course_enrollment_free
          ON course_enrollments(user_id, course_id)
          WHERE entitlement_id IS NULL AND status <> 'revoked';
        CREATE TABLE course_inbox_events (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          source_event_id UUID NOT NULL UNIQUE,
          event_type VARCHAR(128) NOT NULL,
          processing_status VARCHAR(32) NOT NULL,
          received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          processed_at TIMESTAMPTZ
        );
        CREATE TABLE course_playback_sessions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id UUID NOT NULL REFERENCES users(id),
          enrollment_id UUID NOT NULL REFERENCES course_enrollments(id),
          lesson_id UUID NOT NULL REFERENCES course_lessons(id),
          video_asset_id UUID NOT NULL REFERENCES course_video_assets(id),
          access_token_hash VARCHAR(128) NOT NULL,
          status VARCHAR(32) NOT NULL,
          started_at TIMESTAMPTZ NOT NULL,
          last_heartbeat_at TIMESTAMPTZ,
          expires_at TIMESTAMPTZ NOT NULL,
          completed_at TIMESTAMPTZ,
          last_position_seconds INTEGER NOT NULL DEFAULT 0 CHECK (last_position_seconds >= 0),
          maximum_position_seconds INTEGER NOT NULL DEFAULT 0 CHECK (maximum_position_seconds >= 0),
          last_sequence INTEGER NOT NULL DEFAULT 0 CHECK (last_sequence >= 0),
          valid_played_seconds INTEGER NOT NULL DEFAULT 0 CHECK (valid_played_seconds >= 0),
          device_session_hash VARCHAR(128),
          ip_address_hash VARCHAR(128),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE lesson_progress (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          enrollment_id UUID NOT NULL REFERENCES course_enrollments(id),
          lesson_id UUID NOT NULL REFERENCES course_lessons(id),
          status VARCHAR(32) NOT NULL DEFAULT 'not_started',
          progress_basis_points INTEGER NOT NULL DEFAULT 0
            CHECK (progress_basis_points BETWEEN 0 AND 10000),
          last_position_seconds INTEGER
            CHECK (last_position_seconds IS NULL OR last_position_seconds >= 0),
          maximum_position_seconds INTEGER
            CHECK (maximum_position_seconds IS NULL OR maximum_position_seconds >= 0),
          started_at TIMESTAMPTZ,
          last_accessed_at TIMESTAMPTZ,
          completed_at TIMESTAMPTZ,
          completion_source VARCHAR(32),
          completion_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
          version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(enrollment_id, lesson_id)
        );
        CREATE TABLE learning_events (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id UUID NOT NULL REFERENCES users(id),
          enrollment_id UUID NOT NULL REFERENCES course_enrollments(id),
          lesson_id UUID REFERENCES course_lessons(id),
          event_type VARCHAR(64) NOT NULL,
          event_sequence BIGINT NOT NULL CHECK (event_sequence > 0),
          idempotency_key VARCHAR(128) NOT NULL,
          event_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
          occurred_at TIMESTAMPTZ NOT NULL,
          received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(enrollment_id, idempotency_key),
          UNIQUE(enrollment_id, event_sequence)
        );
        CREATE INDEX ix_course_enrollments_user ON course_enrollments(user_id, status, enrolled_at);
        CREATE INDEX ix_playback_active_user
          ON course_playback_sessions(user_id, status, expires_at);
        CREATE INDEX ix_learning_events_enrollment ON learning_events(enrollment_id, received_at);
        """
    )


def downgrade() -> None:
    _run(
        """
        DROP TABLE learning_events;
        DROP TABLE lesson_progress;
        DROP TABLE course_playback_sessions;
        DROP TABLE course_inbox_events;
        DROP TABLE course_enrollments;
        DROP TABLE lesson_video_resources;
        DROP TABLE course_video_assets;
        """
    )
