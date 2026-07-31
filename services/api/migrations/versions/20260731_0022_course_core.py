"""Create course publication and localization core.

Revision ID: 20260731_0022
Revises: 20260731_0021
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260731_0022"
down_revision: str | None = "20260731_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _run(sql: str) -> None:
    for statement in sql.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(
        """
        CREATE TABLE course_completion_policies (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          policy_code VARCHAR(128) NOT NULL UNIQUE,
          policy_version INTEGER NOT NULL CHECK (policy_version > 0),
          required_lesson_completion_basis_points INTEGER NOT NULL DEFAULT 10000
            CHECK (required_lesson_completion_basis_points BETWEEN 0 AND 10000),
          require_all_required_lessons BOOLEAN NOT NULL DEFAULT TRUE,
          required_exercise_pass_basis_points INTEGER
            CHECK (required_exercise_pass_basis_points BETWEEN 0 AND 10000),
          require_all_required_exercises BOOLEAN NOT NULL DEFAULT FALSE,
          minimum_total_score_basis_points INTEGER
            CHECK (minimum_total_score_basis_points BETWEEN 0 AND 10000),
          certificate_enabled BOOLEAN NOT NULL DEFAULT FALSE,
          policy_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE courses (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          course_code VARCHAR(128) NOT NULL UNIQUE,
          internal_name VARCHAR(200) NOT NULL,
          course_type VARCHAR(32) NOT NULL,
          status VARCHAR(32) NOT NULL DEFAULT 'draft',
          visibility VARCHAR(32) NOT NULL DEFAULT 'public',
          default_locale VARCHAR(16) NOT NULL,
          difficulty_level VARCHAR(32),
          estimated_duration_minutes INTEGER
            CHECK (estimated_duration_minutes IS NULL OR estimated_duration_minutes >= 0),
          enrollment_opens_at TIMESTAMPTZ,
          enrollment_closes_at TIMESTAMPTZ,
          content_release_policy VARCHAR(32) NOT NULL DEFAULT 'all_at_once',
          unpublished_access_policy VARCHAR(64) NOT NULL DEFAULT 'block_new_enrollment_only',
          free_access_policy VARCHAR(32),
          catalog_product_id UUID REFERENCES products(id),
          primary_catalog_sku_id UUID REFERENCES product_skus(id),
          completion_policy_id UUID REFERENCES course_completion_policies(id),
          featured BOOLEAN NOT NULL DEFAULT FALSE,
          sort_order INTEGER NOT NULL DEFAULT 0,
          created_by UUID NOT NULL REFERENCES users(id),
          updated_by UUID NOT NULL REFERENCES users(id),
          version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          archived_at TIMESTAMPTZ,
          CHECK (enrollment_opens_at IS NULL OR enrollment_closes_at IS NULL
                 OR enrollment_closes_at > enrollment_opens_at)
        );
        CREATE TABLE course_localizations (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
          locale VARCHAR(16) NOT NULL,
          slug VARCHAR(200) NOT NULL,
          title VARCHAR(300) NOT NULL,
          subtitle VARCHAR(500),
          summary TEXT,
          description_blocks JSONB NOT NULL DEFAULT '[]'::jsonb,
          learning_outcomes JSONB NOT NULL DEFAULT '[]'::jsonb,
          target_audience JSONB NOT NULL DEFAULT '[]'::jsonb,
          prerequisites JSONB NOT NULL DEFAULT '[]'::jsonb,
          instructor_summary TEXT,
          refund_notice TEXT,
          seo_title VARCHAR(300),
          seo_description VARCHAR(500),
          cover_media_id UUID REFERENCES media_assets(id),
          translation_status VARCHAR(32) NOT NULL DEFAULT 'draft',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(course_id, locale),
          UNIQUE(locale, slug)
        );
        CREATE TABLE course_instructors (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          instructor_code VARCHAR(128) NOT NULL UNIQUE,
          linked_user_id UUID REFERENCES users(id),
          display_name VARCHAR(200) NOT NULL,
          status VARCHAR(32) NOT NULL DEFAULT 'active',
          avatar_media_id UUID REFERENCES media_assets(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE course_instructor_assignments (
          course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
          instructor_id UUID NOT NULL REFERENCES course_instructors(id),
          role VARCHAR(64) NOT NULL,
          sort_order INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(course_id, instructor_id, role)
        );
        CREATE INDEX ix_courses_public_catalog
          ON courses(status, visibility, featured, sort_order);
        """
    )


def downgrade() -> None:
    _run(
        """
        DROP TABLE course_instructor_assignments;
        DROP TABLE course_instructors;
        DROP TABLE course_localizations;
        DROP TABLE courses;
        DROP TABLE course_completion_policies;
        """
    )
