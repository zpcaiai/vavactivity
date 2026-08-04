"""Add dating-profile completeness snapshots, review cases, items and audit events.

Revision ID: 20260804_0052
Revises: 20260804_0051
"""

# ruff: noqa: E501

from alembic import op

revision = "20260804_0052"
down_revision = "20260804_0051"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE dating_profile_completeness_snapshots (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      dating_profile_id UUID NOT NULL REFERENCES dating_profiles(id) ON DELETE CASCADE,
      profile_version_number INTEGER NOT NULL,
      policy_version VARCHAR(64) NOT NULL,
      total_basis_points INTEGER NOT NULL CHECK(total_basis_points BETWEEN 0 AND 10000),
      section_scores JSONB NOT NULL,
      missing_required_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
      missing_recommended_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
      submission_eligible BOOLEAN NOT NULL,
      recommendation_eligible BOOLEAN NOT NULL,
      evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(dating_profile_id, profile_version_number)
    );
    CREATE TABLE dating_profile_review_cases (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      dating_profile_id UUID NOT NULL REFERENCES dating_profiles(id) ON DELETE CASCADE,
      profile_version_id UUID NOT NULL REFERENCES dating_profile_versions(id) ON DELETE CASCADE,
      review_type VARCHAR(32) NOT NULL,
      status VARCHAR(32) NOT NULL,
      priority VARCHAR(32) NOT NULL DEFAULT 'normal',
      assigned_to UUID REFERENCES users(id),
      assigned_at TIMESTAMPTZ,
      submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      started_at TIMESTAMPTZ,
      completed_at TIMESTAMPTZ,
      overall_decision VARCHAR(32),
      user_message_safe TEXT,
      internal_summary_encrypted TEXT,
      version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(profile_version_id, review_type)
    );
    CREATE INDEX ix_dating_review_cases_queue ON dating_profile_review_cases(status, priority, submitted_at);
    CREATE TABLE dating_profile_review_items (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      review_case_id UUID NOT NULL REFERENCES dating_profile_review_cases(id) ON DELETE CASCADE,
      item_type VARCHAR(32) NOT NULL,
      field_code VARCHAR(128),
      photo_id UUID REFERENCES dating_profile_photos(id) ON DELETE SET NULL,
      decision VARCHAR(32) NOT NULL,
      reason_code VARCHAR(128),
      user_message_safe TEXT,
      internal_note_encrypted TEXT,
      reviewed_by UUID NOT NULL REFERENCES users(id),
      reviewed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CHECK (field_code IS NOT NULL OR photo_id IS NOT NULL)
    );
    CREATE INDEX ix_dating_review_items_case ON dating_profile_review_items(review_case_id, reviewed_at);
    CREATE TABLE matchmaking_audit_events (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      event_type VARCHAR(128) NOT NULL,
      actor_id UUID REFERENCES users(id),
      subject_type VARCHAR(64) NOT NULL,
      subject_id UUID,
      reason TEXT,
      safe_context JSONB NOT NULL DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_matchmaking_audit_subject ON matchmaking_audit_events(subject_type, subject_id, created_at DESC);
    CREATE INDEX ix_matchmaking_audit_type ON matchmaking_audit_events(event_type, created_at DESC);
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE matchmaking_audit_events;
    DROP TABLE dating_profile_review_items;
    DROP TABLE dating_profile_review_cases;
    DROP TABLE dating_profile_completeness_snapshots;
    """)
