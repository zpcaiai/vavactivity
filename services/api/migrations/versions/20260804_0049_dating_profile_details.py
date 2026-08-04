"""Add dating-profile faith, relationship history, family, lifestyle and narratives.

Revision ID: 20260804_0049
Revises: 20260804_0048
"""

# ruff: noqa: E501

from alembic import op

revision = "20260804_0049"
down_revision = "20260804_0048"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE dating_profile_faith_details (
      dating_profile_id UUID PRIMARY KEY REFERENCES dating_profiles(id) ON DELETE CASCADE,
      faith_status_code VARCHAR(128),
      faith_started_year INTEGER CHECK(faith_started_year IS NULL OR faith_started_year BETWEEN 1900 AND 2200),
      church_tradition_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
      current_church_participation_code VARCHAR(128),
      devotional_life_code VARCHAR(128),
      small_group_participation_code VARCHAR(128),
      ministry_participation_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
      marriage_faith_importance INTEGER CHECK(marriage_faith_importance IS NULL OR marriage_faith_importance BETWEEN 1 AND 5),
      future_church_expectation_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
      faith_journey_summary_encrypted TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE dating_profile_relationship_history (
      dating_profile_id UUID PRIMARY KEY REFERENCES dating_profiles(id) ON DELETE CASCADE,
      marital_status_code VARCHAR(128),
      prior_marriage_count INTEGER CHECK(prior_marriage_count IS NULL OR prior_marriage_count BETWEEN 0 AND 20),
      relationship_history_disclosure_level VARCHAR(64) NOT NULL DEFAULT 'after_mutual_match',
      has_children BOOLEAN,
      children_count_range VARCHAR(64),
      children_living_arrangement_code VARCHAR(128),
      open_to_partner_with_children VARCHAR(64),
      history_summary_encrypted TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE dating_profile_family_details (
      dating_profile_id UUID PRIMARY KEY REFERENCES dating_profiles(id) ON DELETE CASCADE,
      current_living_arrangement_code VARCHAR(128),
      family_closeness_code VARCHAR(128),
      family_culture_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
      parental_care_expectation_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
      desire_children_code VARCHAR(128),
      parenting_expectation_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
      preferred_future_household_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
      family_summary_encrypted TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE dating_profile_lifestyle_details (
      dating_profile_id UUID PRIMARY KEY REFERENCES dating_profiles(id) ON DELETE CASCADE,
      daily_schedule_code VARCHAR(128),
      diet_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
      exercise_frequency_code VARCHAR(128),
      smoking_status_code VARCHAR(128),
      alcohol_use_code VARCHAR(128),
      social_style_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
      leisure_interest_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
      pet_preference_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
      travel_frequency_code VARCHAR(128),
      financial_attitude_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
      conflict_style_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
      communication_preference_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE dating_profile_narratives (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      dating_profile_id UUID NOT NULL REFERENCES dating_profiles(id) ON DELETE CASCADE,
      locale VARCHAR(16) NOT NULL,
      self_introduction TEXT,
      faith_journey TEXT,
      relationship_values TEXT,
      marriage_vision TEXT,
      family_vision TEXT,
      strengths_and_growth TEXT,
      interests_and_lifestyle TEXT,
      hoped_for_relationship TEXT,
      moderation_status VARCHAR(32) NOT NULL DEFAULT 'review_required',
      moderation_findings JSONB NOT NULL DEFAULT '[]'::jsonb,
      ai_assisted BOOLEAN NOT NULL DEFAULT false,
      ai_assistance_confirmed_at TIMESTAMPTZ,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(dating_profile_id, locale)
    );
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE dating_profile_narratives;
    DROP TABLE dating_profile_lifestyle_details;
    DROP TABLE dating_profile_family_details;
    DROP TABLE dating_profile_relationship_history;
    DROP TABLE dating_profile_faith_details;
    """)
