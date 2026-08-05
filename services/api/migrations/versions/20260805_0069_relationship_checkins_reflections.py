"""Add optional check-ins, private reflections and consensual action items.

Revision ID: 20260805_0069
Revises: 20260805_0068
"""

# ruff: noqa: E501

from alembic import op

revision = "20260805_0069"
down_revision = "20260805_0068"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE relationship_checkin_definitions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      definition_code VARCHAR(64) NOT NULL,
      definition_version VARCHAR(32) NOT NULL,
      status VARCHAR(32) NOT NULL DEFAULT 'draft',
      manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      activated_at TIMESTAMPTZ,
      UNIQUE(definition_code, definition_version)
    );
    CREATE TABLE relationship_checkins (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      journey_id UUID NOT NULL REFERENCES relationship_journeys(id) ON DELETE CASCADE,
      definition_id UUID REFERENCES relationship_checkin_definitions(id),
      initiated_by_user_id UUID NOT NULL REFERENCES users(id),
      visibility VARCHAR(32) NOT NULL DEFAULT 'private',
      status VARCHAR(32) NOT NULL DEFAULT 'open',
      scheduled_for TIMESTAMPTZ,
      completed_at TIMESTAMPTZ,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CHECK (visibility IN ('private','shared'))
    );
    CREATE TABLE relationship_checkin_responses (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      checkin_id UUID NOT NULL REFERENCES relationship_checkins(id) ON DELETE CASCADE,
      respondent_user_id UUID NOT NULL REFERENCES users(id),
      response_encrypted TEXT NOT NULL,
      submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(checkin_id, respondent_user_id)
    );
    CREATE TABLE relationship_reflections (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      journey_id UUID NOT NULL REFERENCES relationship_journeys(id) ON DELETE CASCADE,
      author_user_id UUID NOT NULL REFERENCES users(id),
      reflection_encrypted TEXT NOT NULL,
      ai_processing_consent_id UUID,
      status VARCHAR(32) NOT NULL DEFAULT 'active',
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      deleted_at TIMESTAMPTZ
    );
    CREATE INDEX ix_relationship_reflections_owner ON relationship_reflections(journey_id, author_user_id, created_at DESC);
    CREATE TABLE relationship_action_items (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      journey_id UUID NOT NULL REFERENCES relationship_journeys(id) ON DELETE CASCADE,
      created_by_user_id UUID NOT NULL REFERENCES users(id),
      assigned_to_user_id UUID NOT NULL REFERENCES users(id),
      title VARCHAR(200) NOT NULL,
      details_encrypted TEXT,
      status VARCHAR(32) NOT NULL DEFAULT 'proposed',
      accepted_at TIMESTAMPTZ,
      completed_at TIMESTAMPTZ,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CHECK (status IN ('proposed','accepted','open','completed','declined','cancelled'))
    );
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE relationship_action_items;
    DROP TABLE relationship_reflections;
    DROP TABLE relationship_checkin_responses;
    DROP TABLE relationship_checkins;
    DROP TABLE relationship_checkin_definitions;
    """)
