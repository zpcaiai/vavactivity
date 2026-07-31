"""Create participant projection and private activity choice tables.

Revision ID: 20260731_0021
Revises: 20260731_0020
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260731_0021"
down_revision: str | None = "20260731_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _run(sql: str) -> None:
    for statement in sql.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(
        """
        CREATE TABLE activity_participant_profiles (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          activity_id UUID NOT NULL REFERENCES activities(id),
          registration_id UUID NOT NULL REFERENCES activity_registrations(id),
          user_id UUID NOT NULL REFERENCES users(id),
          dating_profile_id UUID,
          display_name VARCHAR(160) NOT NULL,
          avatar_media_id UUID REFERENCES media_assets(id),
          brief_introduction VARCHAR(500),
          visibility_status VARCHAR(32) NOT NULL,
          profile_snapshot_version INTEGER,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(activity_id, user_id)
        );
        CREATE TABLE activity_post_event_choices (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          activity_id UUID NOT NULL REFERENCES activities(id),
          chooser_user_id UUID NOT NULL REFERENCES users(id),
          chosen_user_id UUID NOT NULL REFERENCES users(id),
          choice VARCHAR(32) NOT NULL,
          status VARCHAR(32) NOT NULL DEFAULT 'active',
          submitted_at TIMESTAMPTZ NOT NULL,
          withdrawn_at TIMESTAMPTZ,
          version INTEGER NOT NULL DEFAULT 1,
          UNIQUE(activity_id, chooser_user_id, chosen_user_id),
          CHECK (chooser_user_id <> chosen_user_id)
        );
        CREATE TABLE activity_interaction_restrictions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_a_id UUID NOT NULL REFERENCES users(id),
          user_b_id UUID NOT NULL REFERENCES users(id),
          status VARCHAR(32) NOT NULL,
          reason_code VARCHAR(128) NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(user_a_id, user_b_id),
          CHECK (user_a_id::text < user_b_id::text)
        );
        CREATE TABLE activity_mutual_choices (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          activity_id UUID NOT NULL REFERENCES activities(id),
          user_a_id UUID NOT NULL REFERENCES users(id),
          user_b_id UUID NOT NULL REFERENCES users(id),
          first_choice_id UUID NOT NULL REFERENCES activity_post_event_choices(id),
          second_choice_id UUID NOT NULL REFERENCES activity_post_event_choices(id),
          status VARCHAR(32) NOT NULL,
          matched_at TIMESTAMPTZ NOT NULL,
          platform_match_id UUID,
          introduction_invitation_id UUID,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(activity_id, user_a_id, user_b_id),
          CHECK (user_a_id <> user_b_id),
          CHECK (user_a_id::text < user_b_id::text)
        );
        """
    )


def downgrade() -> None:
    _run(
        """
        DROP TABLE activity_mutual_choices;
        DROP TABLE activity_interaction_restrictions;
        DROP TABLE activity_post_event_choices;
        DROP TABLE activity_participant_profiles;
        """
    )
