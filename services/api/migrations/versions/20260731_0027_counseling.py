"""Add counseling mentors, scheduling, appointments, delivery and records.

Revision ID: 20260731_0027
Revises: 20260731_0026
"""

# ruff: noqa: E501

from alembic import op

revision = "20260731_0027"
down_revision = "20260731_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    statements = """
        CREATE TABLE counseling_mentors (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(), mentor_code varchar(128) UNIQUE NOT NULL,
          linked_user_id uuid REFERENCES users(id), display_name varchar(200) NOT NULL,
          status varchar(32) NOT NULL DEFAULT 'draft', timezone varchar(64) NOT NULL,
          service_languages jsonb NOT NULL DEFAULT '[]', specialty_topics jsonb NOT NULL DEFAULT '[]',
          internal_profile_encrypted text, created_by uuid NOT NULL REFERENCES users(id),
          version integer NOT NULL DEFAULT 1, created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(), archived_at timestamptz
        );
        CREATE TABLE counseling_mentor_localizations (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(), mentor_id uuid NOT NULL REFERENCES counseling_mentors(id),
          locale varchar(16) NOT NULL, slug varchar(200) NOT NULL, public_name varchar(200) NOT NULL,
          headline varchar(500), biography_blocks jsonb NOT NULL DEFAULT '[]', scope_statement text NOT NULL,
          translation_status varchar(32) NOT NULL DEFAULT 'draft', created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(), UNIQUE(mentor_id, locale), UNIQUE(locale, slug)
        );
        CREATE TABLE counseling_services (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(), service_code varchar(128) UNIQUE NOT NULL,
          internal_name varchar(200) NOT NULL, status varchar(32) NOT NULL DEFAULT 'draft',
          delivery_mode varchar(32) NOT NULL, participant_mode varchar(32) NOT NULL,
          duration_minutes integer NOT NULL CHECK(duration_minutes > 0),
          buffer_before_minutes integer NOT NULL DEFAULT 0, buffer_after_minutes integer NOT NULL DEFAULT 0,
          booking_mode varchar(32) NOT NULL DEFAULT 'request_and_confirm', payment_policy varchar(32) NOT NULL,
          free_access boolean NOT NULL DEFAULT false, catalog_product_id uuid REFERENCES products(id),
          catalog_sku_id uuid REFERENCES product_skus(id), cancellation_policy jsonb NOT NULL DEFAULT '{}',
          no_show_policy jsonb NOT NULL DEFAULT '{}', scope_policy jsonb NOT NULL DEFAULT '{}',
          min_notice_minutes integer NOT NULL DEFAULT 1440, max_advance_days integer NOT NULL DEFAULT 90,
          created_by uuid NOT NULL REFERENCES users(id), version integer NOT NULL DEFAULT 1,
          created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE counseling_service_localizations (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(), service_id uuid NOT NULL REFERENCES counseling_services(id),
          locale varchar(16) NOT NULL, slug varchar(200) NOT NULL, name varchar(300) NOT NULL, summary text,
          description_blocks jsonb NOT NULL DEFAULT '[]', scope_notice text NOT NULL,
          translation_status varchar(32) NOT NULL DEFAULT 'draft', UNIQUE(service_id, locale), UNIQUE(locale, slug)
        );
        CREATE TABLE counseling_mentor_services (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(), mentor_id uuid NOT NULL REFERENCES counseling_mentors(id),
          service_id uuid NOT NULL REFERENCES counseling_services(id), status varchar(32) NOT NULL DEFAULT 'active',
          UNIQUE(mentor_id, service_id)
        );
        CREATE TABLE counseling_availability_rules (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(), mentor_id uuid NOT NULL REFERENCES counseling_mentors(id),
          service_id uuid REFERENCES counseling_services(id), timezone varchar(64) NOT NULL,
          weekday integer NOT NULL CHECK(weekday BETWEEN 0 AND 6), local_start_time time NOT NULL,
          local_end_time time NOT NULL, valid_from date NOT NULL, valid_until date,
          daily_limit integer, weekly_limit integer, status varchar(32) NOT NULL DEFAULT 'active',
          CHECK(local_end_time > local_start_time)
        );
        CREATE TABLE counseling_availability_overrides (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(), mentor_id uuid NOT NULL REFERENCES counseling_mentors(id),
          starts_at timestamptz NOT NULL, ends_at timestamptz NOT NULL, override_type varchar(32) NOT NULL,
          reason_encrypted text, CHECK(ends_at > starts_at)
        );
        CREATE TABLE counseling_slot_holds (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(), mentor_id uuid NOT NULL REFERENCES counseling_mentors(id),
          service_id uuid NOT NULL REFERENCES counseling_services(id), user_id uuid NOT NULL REFERENCES users(id),
          starts_at timestamptz NOT NULL, ends_at timestamptz NOT NULL, status varchar(32) NOT NULL,
          idempotency_key varchar(128) UNIQUE NOT NULL, expires_at timestamptz NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(), CHECK(ends_at > starts_at)
        );
        CREATE TABLE counseling_appointments (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(), appointment_number varchar(64) UNIQUE NOT NULL,
          user_id uuid NOT NULL REFERENCES users(id), mentor_id uuid REFERENCES counseling_mentors(id),
          service_id uuid NOT NULL REFERENCES counseling_services(id), slot_hold_id uuid REFERENCES counseling_slot_holds(id),
          status varchar(32) NOT NULL, scheduled_starts_at timestamptz, scheduled_ends_at timestamptz,
          user_timezone varchar(64) NOT NULL, intake_schema_version integer NOT NULL,
          intake_response_encrypted text NOT NULL, payment_status varchar(32) NOT NULL DEFAULT 'not_required',
          entitlement_id uuid REFERENCES entitlements(id), credit_reservation_status varchar(32),
          cancellation_policy_snapshot jsonb NOT NULL, no_show_policy_snapshot jsonb NOT NULL,
          idempotency_key varchar(128) NOT NULL, proposal_version integer NOT NULL DEFAULT 0,
          version integer NOT NULL DEFAULT 1, created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(), UNIQUE(user_id, idempotency_key),
          CHECK(scheduled_ends_at IS NULL OR scheduled_starts_at IS NULL OR scheduled_ends_at > scheduled_starts_at)
        );
        ALTER TABLE counseling_appointments ADD CONSTRAINT counseling_appointments_no_overlap
          EXCLUDE USING gist (mentor_id WITH =, tstzrange(scheduled_starts_at, scheduled_ends_at, '[)') WITH &&)
          WHERE (status IN ('confirmed','reschedule_requested'));
        CREATE TABLE counseling_appointment_history (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(), appointment_id uuid NOT NULL REFERENCES counseling_appointments(id),
          from_status varchar(32), to_status varchar(32) NOT NULL, actor_id uuid REFERENCES users(id),
          reason text, created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE counseling_sessions (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(), appointment_id uuid UNIQUE NOT NULL REFERENCES counseling_appointments(id),
          status varchar(32) NOT NULL, meeting_reference_encrypted text, private_location_encrypted text,
          recording_enabled boolean NOT NULL DEFAULT false, transcription_enabled boolean NOT NULL DEFAULT false,
          started_at timestamptz, completed_at timestamptz, completion_key varchar(128) UNIQUE,
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE counseling_records (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(), session_id uuid NOT NULL REFERENCES counseling_sessions(id),
          record_type varchar(32) NOT NULL, visibility varchar(32) NOT NULL, version integer NOT NULL DEFAULT 1,
          status varchar(32) NOT NULL DEFAULT 'draft', content_encrypted text NOT NULL,
          created_by uuid NOT NULL REFERENCES users(id), published_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE counseling_follow_ups (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(), appointment_id uuid NOT NULL REFERENCES counseling_appointments(id),
          user_id uuid NOT NULL REFERENCES users(id), assigned_to uuid REFERENCES users(id),
          follow_up_type varchar(32) NOT NULL, status varchar(32) NOT NULL, due_at timestamptz,
          content_encrypted text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE counseling_safety_referrals (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(), appointment_id uuid NOT NULL REFERENCES counseling_appointments(id),
          risk_level varchar(32) NOT NULL, category varchar(64) NOT NULL, details_encrypted text NOT NULL,
          status varchar(32) NOT NULL, created_by uuid NOT NULL REFERENCES users(id),
          created_at timestamptz NOT NULL DEFAULT now()
        );
        """
    for statement in statements.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    for table in (
        "counseling_safety_referrals",
        "counseling_follow_ups",
        "counseling_records",
        "counseling_sessions",
        "counseling_appointment_history",
        "counseling_appointments",
        "counseling_slot_holds",
        "counseling_availability_overrides",
        "counseling_availability_rules",
        "counseling_mentor_services",
        "counseling_service_localizations",
        "counseling_services",
        "counseling_mentor_localizations",
        "counseling_mentors",
    ):
        op.execute(f"DROP TABLE {table}")
