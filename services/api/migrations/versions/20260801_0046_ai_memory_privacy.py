"""Add privacy-governed AI memory.

Revision ID: 20260801_0046
Revises: 20260801_0045
"""

# ruff: noqa: E501

from alembic import op

revision = "20260801_0046"
down_revision = "20260801_0045"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE ai_memory_preferences (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL UNIQUE REFERENCES users(id),
      long_term_memory_enabled BOOLEAN NOT NULL DEFAULT false, allow_profile_facts BOOLEAN NOT NULL DEFAULT false,
      allow_service_history BOOLEAN NOT NULL DEFAULT false, allow_relationship_context BOOLEAN NOT NULL DEFAULT false,
      allow_cross_conversation_use BOOLEAN NOT NULL DEFAULT false, consent_id UUID REFERENCES user_consents(id),
      settings_version INTEGER NOT NULL DEFAULT 1, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE ai_memory_items (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL REFERENCES users(id),
      memory_type VARCHAR(64) NOT NULL, status VARCHAR(32) NOT NULL, content_encrypted TEXT NOT NULL,
      content_hmac VARCHAR(128) NOT NULL, source_type VARCHAR(64) NOT NULL, source_reference_id UUID,
      provenance_snapshot JSONB NOT NULL, certainty VARCHAR(32) NOT NULL,
      user_confirmed BOOLEAN NOT NULL DEFAULT false, allowed_purposes JSONB NOT NULL,
      allowed_agent_profiles JSONB NOT NULL, valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
      expires_at TIMESTAMPTZ, last_used_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), deleted_at TIMESTAMPTZ
    );
    CREATE INDEX ix_ai_memory_user_status ON ai_memory_items(user_id,status,created_at DESC);
    CREATE UNIQUE INDEX uq_active_ai_memory_content ON ai_memory_items(user_id,content_hmac)
      WHERE status IN ('candidate','user_approval_required','active');
    CREATE TABLE ai_memory_cleanup_events (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL REFERENCES users(id),
      memory_item_id UUID REFERENCES ai_memory_items(id), cleanup_type VARCHAR(32) NOT NULL,
      vector_removed BOOLEAN NOT NULL, cache_invalidated BOOLEAN NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE ai_memory_cleanup_events;
    DROP TABLE ai_memory_items;
    DROP TABLE ai_memory_preferences;
    """)
