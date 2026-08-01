"""Add privacy requests, exports and corrections.

Revision ID: 20260801_0043
Revises: 20260801_0042
"""

# ruff: noqa: E501

from alembic import op

revision = "20260801_0043"
down_revision = "20260801_0042"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE data_subject_requests (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), request_number VARCHAR(64) NOT NULL UNIQUE,
      user_id UUID NOT NULL REFERENCES users(id), request_type VARCHAR(32) NOT NULL, status VARCHAR(32) NOT NULL,
      requested_scope JSONB NOT NULL, requested_format VARCHAR(32), identity_verification_level VARCHAR(32) NOT NULL,
      identity_verified_at TIMESTAMPTZ, reauthenticated_at TIMESTAMPTZ, submitted_at TIMESTAMPTZ NOT NULL,
      due_at TIMESTAMPTZ, assigned_to UUID REFERENCES users(id), decision_code VARCHAR(128),
      decision_reason_safe TEXT, completed_at TIMESTAMPTZ,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_data_subject_requests_user ON data_subject_requests(user_id,created_at DESC);
    CREATE UNIQUE INDEX uq_active_subject_request_type ON data_subject_requests(user_id,request_type)
      WHERE status IN ('submitted','identity_verification_required','verified','in_review','approved','processing','partially_completed');
    CREATE TABLE privacy_request_events (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), data_subject_request_id UUID NOT NULL REFERENCES data_subject_requests(id),
      event_type VARCHAR(128) NOT NULL, actor_id UUID REFERENCES users(id), safe_context JSONB NOT NULL DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE privacy_export_jobs (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), data_subject_request_id UUID NOT NULL UNIQUE REFERENCES data_subject_requests(id),
      status VARCHAR(32) NOT NULL, export_format VARCHAR(32) NOT NULL, module_manifest JSONB NOT NULL,
      completed_modules JSONB NOT NULL DEFAULT '[]'::jsonb, failed_modules JSONB NOT NULL DEFAULT '[]'::jsonb,
      archive_media_id UUID REFERENCES media_assets(id), archive_encrypted BYTEA, archive_checksum_sha256 VARCHAR(64),
      encryption_mode VARCHAR(32) NOT NULL, download_token_hash VARCHAR(128), download_expires_at TIMESTAMPTZ,
      downloaded_at TIMESTAMPTZ, archive_expires_at TIMESTAMPTZ, started_at TIMESTAMPTZ,
      completed_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE privacy_module_request_results (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), data_subject_request_id UUID NOT NULL REFERENCES data_subject_requests(id),
      module_code VARCHAR(64) NOT NULL, operation VARCHAR(32) NOT NULL, status VARCHAR(32) NOT NULL,
      schema_version VARCHAR(32) NOT NULL, result_manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
      error_code VARCHAR(128), attempts INTEGER NOT NULL DEFAULT 0, completed_at TIMESTAMPTZ,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(data_subject_request_id,module_code,operation)
    );
    CREATE TABLE privacy_correction_items (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), data_subject_request_id UUID NOT NULL REFERENCES data_subject_requests(id),
      module_code VARCHAR(64) NOT NULL, entity_reference_type VARCHAR(64) NOT NULL, entity_reference_id UUID,
      field_path VARCHAR(500) NOT NULL, current_value_snapshot_encrypted TEXT,
      requested_value_encrypted TEXT NOT NULL, reason TEXT NOT NULL, status VARCHAR(32) NOT NULL,
      reviewed_by UUID REFERENCES users(id), reviewed_at TIMESTAMPTZ, resolution_code VARCHAR(128),
      resolution_message_safe TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE privacy_correction_items;
    DROP TABLE privacy_module_request_results;
    DROP TABLE privacy_export_jobs;
    DROP TABLE privacy_request_events;
    DROP TABLE data_subject_requests;
    """)
