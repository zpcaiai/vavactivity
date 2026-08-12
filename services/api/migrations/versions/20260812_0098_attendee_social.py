# ruff: noqa: E501

"""Attendee-preview consent and the follow graph.

Covers ATT-001 and SOC-001.

Revision ID: 20260812_0098
Revises: 20260812_0097
"""

from alembic import op

revision = "20260812_0098"
down_revision = "20260812_0097"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(
        """
        -- ATT-001 / DEC-002. Consent is opt-in: 'not_asked' is both the default
        -- value and the meaning of a missing row, so no backfill can turn
        -- silence into permission.
        CREATE TABLE attendee_preview_consents (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          registration_id UUID NOT NULL REFERENCES activity_registrations(id) ON DELETE CASCADE,
          activity_id UUID NOT NULL REFERENCES activities(id),
          user_id UUID NOT NULL REFERENCES users(id),
          consent_state VARCHAR(16) NOT NULL DEFAULT 'not_asked',
          granted_at TIMESTAMPTZ,
          withdrawn_at TIMESTAMPTZ,
          intro_line_encrypted TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (registration_id),
          CHECK (consent_state IN ('not_asked','granted','declined','withdrawn')),
          CHECK (consent_state <> 'granted' OR granted_at IS NOT NULL),
          CHECK (consent_state <> 'withdrawn' OR withdrawn_at IS NOT NULL)
        );
        CREATE INDEX attendee_preview_consents_activity_idx
          ON attendee_preview_consents (activity_id, consent_state);

        -- Append-only. A withdrawal is a recorded event, not an edit of the
        -- original answer, so "who was visible when" stays answerable.
        CREATE TABLE attendee_preview_consent_history (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          registration_id UUID NOT NULL,
          user_id UUID NOT NULL REFERENCES users(id),
          from_state VARCHAR(16),
          to_state VARCHAR(16) NOT NULL,
          actor_id UUID REFERENCES users(id),
          actor_kind VARCHAR(16) NOT NULL,
          reason TEXT,
          note_encrypted TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (actor_kind IN ('member','admin','system')),
          CHECK (to_state IN ('not_asked','granted','declined','withdrawn'))
        );
        CREATE INDEX attendee_preview_consent_history_reg_idx
          ON attendee_preview_consent_history (registration_id, created_at DESC);

        -- SOC-001. A follow is its own table with its own semantics. Likes live
        -- in activity_selection_items (post-event module) and want-to-meet gets
        -- its own table below: three relations, three stores, no shared 'kind'
        -- column that a future refactor could collapse.
        CREATE TABLE social_follows (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          follower_id UUID NOT NULL REFERENCES users(id),
          followee_id UUID NOT NULL REFERENCES users(id),
          state VARCHAR(16) NOT NULL DEFAULT 'active',
          followed_at TIMESTAMPTZ,
          unfollowed_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (follower_id, followee_id),
          CHECK (follower_id <> followee_id),
          CHECK (state IN ('active','unfollowed','blocked'))
        );
        CREATE INDEX social_follows_followee_idx
          ON social_follows (followee_id, state);
        CREATE INDEX social_follows_follower_idx
          ON social_follows (follower_id, state);

        CREATE TABLE social_want_to_meet (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id UUID NOT NULL REFERENCES users(id),
          target_user_id UUID NOT NULL REFERENCES users(id),
          activity_id UUID NOT NULL REFERENCES activities(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (user_id, target_user_id, activity_id),
          CHECK (user_id <> target_user_id)
        );
        CREATE INDEX social_want_to_meet_activity_idx
          ON social_want_to_meet (activity_id);

        CREATE TABLE social_notification_preferences (
          user_id UUID PRIMARY KEY REFERENCES users(id),
          followed_user_registered BOOLEAN NOT NULL DEFAULT true,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        -- SOC-001. The unique dedupe_key is the idempotent delivery key: a
        -- retried fan-out inserts nothing and therefore sends nothing.
        CREATE TABLE social_notification_deliveries (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          dedupe_key VARCHAR(255) NOT NULL,
          recipient_id UUID NOT NULL REFERENCES users(id),
          actor_id UUID NOT NULL REFERENCES users(id),
          activity_id UUID REFERENCES activities(id),
          notification_code VARCHAR(64) NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (dedupe_key),
          CHECK (recipient_id <> actor_id)
        );
        CREATE INDEX social_notification_deliveries_recipient_idx
          ON social_notification_deliveries (recipient_id, created_at DESC);

        CREATE TABLE attendee_social_audits (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          subject_user_id UUID REFERENCES users(id),
          activity_id UUID REFERENCES activities(id),
          actor_id UUID REFERENCES users(id),
          actor_kind VARCHAR(16) NOT NULL,
          action VARCHAR(128) NOT NULL,
          reason TEXT,
          metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (actor_kind IN ('member','admin','system'))
        );
        CREATE INDEX attendee_social_audits_subject_idx
          ON attendee_social_audits (subject_user_id, created_at DESC);
        """
    )

    # Deliberately no backfill of attendee_preview_consents. Creating rows for
    # existing registrations would either invent an answer nobody gave, or add
    # millions of rows that mean exactly what their absence already means. The
    # preview treats a missing row as 'not_asked', which is a refusal (DEC-002).


def downgrade() -> None:
    _run(
        """
        DROP TABLE IF EXISTS attendee_social_audits;
        DROP TABLE IF EXISTS social_notification_deliveries;
        DROP TABLE IF EXISTS social_notification_preferences;
        DROP TABLE IF EXISTS social_want_to_meet;
        DROP TABLE IF EXISTS social_follows;
        DROP TABLE IF EXISTS attendee_preview_consent_history;
        DROP TABLE IF EXISTS attendee_preview_consents;
        """
    )
