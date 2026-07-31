"""Create course completion records and certificates.

Revision ID: 20260731_0026
Revises: 20260731_0025
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260731_0026"
down_revision: str | None = "20260731_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _run(sql: str) -> None:
    for statement in sql.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(
        """
        CREATE TABLE course_completion_records (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          enrollment_id UUID NOT NULL UNIQUE REFERENCES course_enrollments(id),
          course_id UUID NOT NULL REFERENCES courses(id),
          course_version_id UUID NOT NULL REFERENCES course_versions(id),
          completion_policy_snapshot JSONB NOT NULL,
          completion_evidence JSONB NOT NULL,
          completed_at TIMESTAMPTZ NOT NULL,
          evaluated_by VARCHAR(32) NOT NULL,
          evaluation_version VARCHAR(64) NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE course_certificates (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          certificate_number VARCHAR(64) NOT NULL UNIQUE,
          completion_record_id UUID NOT NULL UNIQUE REFERENCES course_completion_records(id),
          user_id UUID NOT NULL REFERENCES users(id),
          course_id UUID NOT NULL REFERENCES courses(id),
          recipient_name_snapshot VARCHAR(300) NOT NULL,
          course_title_snapshot VARCHAR(300) NOT NULL,
          issued_at TIMESTAMPTZ NOT NULL,
          status VARCHAR(32) NOT NULL,
          verification_token_hash VARCHAR(128) NOT NULL UNIQUE,
          certificate_document_media_id UUID REFERENCES media_assets(id),
          revoked_at TIMESTAMPTZ,
          revoked_by UUID REFERENCES users(id),
          revoke_reason TEXT,
          replaced_by_certificate_id UUID REFERENCES course_certificates(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_course_certificates_user ON course_certificates(user_id, issued_at);
        """
    )


def downgrade() -> None:
    _run(
        """
        DROP TABLE course_certificates;
        DROP TABLE course_completion_records;
        """
    )
