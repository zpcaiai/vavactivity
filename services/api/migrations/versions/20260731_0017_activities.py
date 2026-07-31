"""Create activity publication, schedule and ticket tables.

Revision ID: 20260731_0017
Revises: 20260731_0016
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260731_0017"
down_revision: str | None = "20260731_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _run(sql: str) -> None:
    for statement in sql.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(
        """
        CREATE TABLE activities (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          activity_code VARCHAR(128) NOT NULL UNIQUE,
          internal_name VARCHAR(200) NOT NULL,
          activity_format VARCHAR(32) NOT NULL,
          status VARCHAR(32) NOT NULL DEFAULT 'draft',
          visibility VARCHAR(32) NOT NULL DEFAULT 'public',
          default_locale VARCHAR(16) NOT NULL,
          timezone VARCHAR(64) NOT NULL,
          registration_opens_at TIMESTAMPTZ,
          registration_closes_at TIMESTAMPTZ,
          starts_at TIMESTAMPTZ NOT NULL,
          ends_at TIMESTAMPTZ NOT NULL,
          post_event_choice_opens_at TIMESTAMPTZ,
          post_event_choice_closes_at TIMESTAMPTZ,
          approval_policy VARCHAR(32) NOT NULL,
          payment_timing_policy VARCHAR(32) NOT NULL,
          waitlist_enabled BOOLEAN NOT NULL DEFAULT TRUE,
          post_event_choice_enabled BOOLEAN NOT NULL DEFAULT FALSE,
          minimum_age INTEGER,
          maximum_age INTEGER,
          cancellation_policy_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_by UUID NOT NULL REFERENCES users(id),
          updated_by UUID NOT NULL REFERENCES users(id),
          version INTEGER NOT NULL DEFAULT 1,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          archived_at TIMESTAMPTZ,
          CHECK (ends_at > starts_at),
          CHECK (registration_opens_at IS NULL OR registration_closes_at IS NULL
                 OR registration_closes_at > registration_opens_at),
          CHECK (registration_closes_at IS NULL OR registration_closes_at <= starts_at),
          CHECK (minimum_age IS NULL OR maximum_age IS NULL OR maximum_age >= minimum_age)
        );
        CREATE TABLE activity_localizations (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          activity_id UUID NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
          locale VARCHAR(16) NOT NULL,
          slug VARCHAR(200) NOT NULL,
          title VARCHAR(300) NOT NULL,
          summary VARCHAR(500),
          description_blocks JSONB NOT NULL DEFAULT '[]'::jsonb,
          venue_display_name VARCHAR(300),
          address_display_text VARCHAR(500),
          participation_notes JSONB NOT NULL DEFAULT '[]'::jsonb,
          cancellation_notice TEXT,
          seo_title VARCHAR(300),
          seo_description VARCHAR(500),
          cover_media_id UUID REFERENCES media_assets(id),
          translation_status VARCHAR(32) NOT NULL DEFAULT 'draft',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(activity_id, locale),
          UNIQUE(locale, slug)
        );
        CREATE TABLE activity_locations (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          activity_id UUID NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
          location_type VARCHAR(32) NOT NULL,
          venue_name VARCHAR(300),
          country_code CHAR(2),
          region VARCHAR(128),
          city VARCHAR(128),
          address_line_1_encrypted TEXT,
          address_line_2_encrypted TEXT,
          postal_code_encrypted TEXT,
          latitude NUMERIC(10,7),
          longitude NUMERIC(10,7),
          online_provider VARCHAR(64),
          online_join_url_encrypted TEXT,
          online_meeting_reference VARCHAR(255),
          public_address_precision VARCHAR(32) NOT NULL DEFAULT 'city_only',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE activity_sessions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          activity_id UUID NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
          session_code VARCHAR(128) NOT NULL,
          title VARCHAR(300) NOT NULL,
          starts_at TIMESTAMPTZ NOT NULL,
          ends_at TIMESTAMPTZ NOT NULL,
          location_id UUID REFERENCES activity_locations(id),
          checkin_opens_at TIMESTAMPTZ,
          checkin_closes_at TIMESTAMPTZ,
          sort_order INTEGER NOT NULL DEFAULT 0,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(activity_id, session_code),
          CHECK (ends_at > starts_at)
        );
        CREATE TABLE activity_ticket_types (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          activity_id UUID NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
          ticket_code VARCHAR(128) NOT NULL,
          internal_name VARCHAR(200) NOT NULL,
          catalog_product_id UUID NOT NULL REFERENCES products(id),
          catalog_sku_id UUID NOT NULL REFERENCES product_skus(id),
          status VARCHAR(32) NOT NULL DEFAULT 'draft',
          registration_opens_at TIMESTAMPTZ,
          registration_closes_at TIMESTAMPTZ,
          approval_policy_override VARCHAR(32),
          payment_timing_override VARCHAR(32),
          waitlist_enabled BOOLEAN NOT NULL DEFAULT TRUE,
          max_quantity_per_user INTEGER NOT NULL DEFAULT 1 CHECK (max_quantity_per_user > 0),
          eligibility_rules JSONB NOT NULL DEFAULT '{}'::jsonb,
          capacity_display_mode VARCHAR(32) NOT NULL DEFAULT 'status_only',
          sort_order INTEGER NOT NULL DEFAULT 0,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(activity_id, ticket_code),
          UNIQUE(activity_id, catalog_sku_id)
        );
        CREATE TABLE activity_ticket_type_localizations (
          ticket_type_id UUID NOT NULL REFERENCES activity_ticket_types(id) ON DELETE CASCADE,
          locale VARCHAR(16) NOT NULL,
          name VARCHAR(200) NOT NULL,
          description VARCHAR(500),
          eligibility_notice TEXT,
          PRIMARY KEY(ticket_type_id, locale)
        );
        CREATE TABLE activity_registration_forms (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          activity_id UUID NOT NULL UNIQUE REFERENCES activities(id) ON DELETE CASCADE,
          schema_version INTEGER NOT NULL CHECK (schema_version > 0),
          form_schema JSONB NOT NULL,
          consent_requirements JSONB NOT NULL DEFAULT '[]'::jsonb,
          created_by UUID NOT NULL REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    _run(
        """
        DROP TABLE activity_registration_forms;
        DROP TABLE activity_ticket_type_localizations;
        DROP TABLE activity_ticket_types;
        DROP TABLE activity_sessions;
        DROP TABLE activity_locations;
        DROP TABLE activity_localizations;
        DROP TABLE activities;
        """
    )
