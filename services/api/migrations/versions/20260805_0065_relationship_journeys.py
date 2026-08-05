"""Create canonical relationship journeys and append-only history.

Revision ID: 20260805_0065
Revises: 20260805_0064
"""

# ruff: noqa: E501

from alembic import op

revision = "20260805_0065"
down_revision = "20260805_0064"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE relationship_journeys (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      journey_number VARCHAR(64) NOT NULL UNIQUE,
      matchmaking_pair_id UUID NOT NULL UNIQUE REFERENCES matchmaking_pairs(id),
      mutual_match_id UUID NOT NULL REFERENCES matchmaking_mutual_matches(id),
      introduction_invitation_id UUID NOT NULL UNIQUE REFERENCES matchmaking_introduction_invitations(id),
      relationship_handoff_id UUID NOT NULL UNIQUE,
      user_low_id UUID NOT NULL REFERENCES users(id),
      user_high_id UUID NOT NULL REFERENCES users(id),
      status VARCHAR(32) NOT NULL DEFAULT 'active',
      current_stage_code VARCHAR(64) NOT NULL DEFAULT 'introduction_accepted',
      stage_registry_version VARCHAR(64) NOT NULL DEFAULT 'relationship-stages-v1',
      policy_version VARCHAR(32) NOT NULL DEFAULT '1.0.0',
      started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      paused_at TIMESTAMPTZ,
      ended_at TIMESTAMPTZ,
      archived_at TIMESTAMPTZ,
      current_pause_id UUID,
      ending_record_id UUID,
      version INTEGER NOT NULL DEFAULT 1,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CHECK (user_low_id::text < user_high_id::text),
      CHECK (status IN ('pending_activation','active','paused','safety_frozen','ended','archived','deletion_pending'))
    );
    CREATE INDEX ix_relationship_journeys_low ON relationship_journeys(user_low_id, status);
    CREATE INDEX ix_relationship_journeys_high ON relationship_journeys(user_high_id, status);

    CREATE TABLE relationship_participants (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      journey_id UUID NOT NULL REFERENCES relationship_journeys(id) ON DELETE CASCADE,
      user_id UUID NOT NULL REFERENCES users(id),
      status VARCHAR(32) NOT NULL DEFAULT 'active',
      joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      personal_state VARCHAR(32) NOT NULL DEFAULT 'participating',
      notification_preferences JSONB NOT NULL DEFAULT '{}'::jsonb,
      last_acknowledged_stage_code VARCHAR(64),
      version INTEGER NOT NULL DEFAULT 1,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(journey_id, user_id)
    );
    CREATE INDEX ix_relationship_participants_user ON relationship_participants(user_id, status);

    CREATE TABLE relationship_status_history (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      journey_id UUID NOT NULL REFERENCES relationship_journeys(id) ON DELETE CASCADE,
      actor_user_id UUID REFERENCES users(id),
      event_type VARCHAR(128) NOT NULL,
      from_status VARCHAR(32),
      to_status VARCHAR(32),
      from_stage_code VARCHAR(64),
      to_stage_code VARCHAR(64),
      reason_code VARCHAR(128),
      safe_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
      source_event_id UUID,
      request_id UUID,
      occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_relationship_history_journey ON relationship_status_history(journey_id, occurred_at DESC);

    CREATE TABLE relationship_inbox_events (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      source_module VARCHAR(64) NOT NULL,
      source_event_id UUID NOT NULL,
      event_type VARCHAR(128) NOT NULL,
      payload JSONB NOT NULL DEFAULT '{}'::jsonb,
      status VARCHAR(32) NOT NULL DEFAULT 'received',
      attempts INTEGER NOT NULL DEFAULT 0,
      received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      processed_at TIMESTAMPTZ,
      error_code VARCHAR(128),
      UNIQUE(source_module, source_event_id)
    );
    CREATE INDEX ix_relationship_inbox_pending ON relationship_inbox_events(status, received_at);
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE relationship_inbox_events;
    DROP TABLE relationship_status_history;
    DROP TABLE relationship_participants;
    DROP TABLE relationship_journeys;
    """)
