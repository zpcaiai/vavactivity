"""Create immutable course versions and curriculum.

Revision ID: 20260731_0023
Revises: 20260731_0022
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260731_0023"
down_revision: str | None = "20260731_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _run(sql: str) -> None:
    for statement in sql.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(
        """
        CREATE TABLE course_versions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
          version_number INTEGER NOT NULL CHECK (version_number > 0),
          curriculum_snapshot JSONB NOT NULL,
          change_summary TEXT NOT NULL,
          created_by UUID NOT NULL REFERENCES users(id),
          published_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(course_id, version_number)
        );
        CREATE TABLE course_modules (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
          module_code VARCHAR(128) NOT NULL,
          internal_name VARCHAR(200) NOT NULL,
          status VARCHAR(32) NOT NULL DEFAULT 'draft',
          sort_order INTEGER NOT NULL,
          release_offset_days INTEGER
            CHECK (release_offset_days IS NULL OR release_offset_days >= 0),
          release_at TIMESTAMPTZ,
          required BOOLEAN NOT NULL DEFAULT TRUE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(course_id, module_code)
        );
        CREATE TABLE course_module_localizations (
          module_id UUID NOT NULL REFERENCES course_modules(id) ON DELETE CASCADE,
          locale VARCHAR(16) NOT NULL,
          title VARCHAR(300) NOT NULL,
          description TEXT,
          PRIMARY KEY(module_id, locale)
        );
        CREATE TABLE course_lessons (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          module_id UUID NOT NULL REFERENCES course_modules(id) ON DELETE CASCADE,
          lesson_code VARCHAR(128) NOT NULL,
          internal_name VARCHAR(200) NOT NULL,
          lesson_type VARCHAR(32) NOT NULL,
          status VARCHAR(32) NOT NULL DEFAULT 'draft',
          sort_order INTEGER NOT NULL,
          required BOOLEAN NOT NULL DEFAULT TRUE,
          preview_policy VARCHAR(32) NOT NULL DEFAULT 'none',
          estimated_duration_minutes INTEGER
            CHECK (estimated_duration_minutes IS NULL OR estimated_duration_minutes >= 0),
          completion_mode VARCHAR(32) NOT NULL,
          completion_threshold JSONB NOT NULL DEFAULT '{}'::jsonb,
          release_offset_days INTEGER
            CHECK (release_offset_days IS NULL OR release_offset_days >= 0),
          release_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(module_id, lesson_code)
        );
        CREATE TABLE course_lesson_localizations (
          lesson_id UUID NOT NULL REFERENCES course_lessons(id) ON DELETE CASCADE,
          locale VARCHAR(16) NOT NULL,
          title VARCHAR(300) NOT NULL,
          summary TEXT,
          content_blocks JSONB NOT NULL DEFAULT '[]'::jsonb,
          PRIMARY KEY(lesson_id, locale)
        );
        CREATE TABLE lesson_prerequisites (
          lesson_id UUID NOT NULL REFERENCES course_lessons(id) ON DELETE CASCADE,
          prerequisite_lesson_id UUID NOT NULL REFERENCES course_lessons(id) ON DELETE CASCADE,
          required_completion BOOLEAN NOT NULL DEFAULT TRUE,
          minimum_score_basis_points INTEGER
            CHECK (minimum_score_basis_points BETWEEN 0 AND 10000),
          PRIMARY KEY(lesson_id, prerequisite_lesson_id),
          CHECK (lesson_id <> prerequisite_lesson_id)
        );
        CREATE TABLE course_sku_mappings (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          catalog_sku_id UUID NOT NULL REFERENCES product_skus(id),
          course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
          access_duration_days INTEGER
            CHECK (access_duration_days IS NULL OR access_duration_days > 0),
          access_start_policy VARCHAR(32) NOT NULL,
          course_version_policy VARCHAR(32) NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(catalog_sku_id, course_id)
        );
        CREATE INDEX ix_course_modules_order ON course_modules(course_id, sort_order, id);
        CREATE INDEX ix_course_lessons_order ON course_lessons(module_id, sort_order, id);
        """
    )


def downgrade() -> None:
    _run(
        """
        DROP TABLE course_sku_mappings;
        DROP TABLE lesson_prerequisites;
        DROP TABLE course_lesson_localizations;
        DROP TABLE course_lessons;
        DROP TABLE course_module_localizations;
        DROP TABLE course_modules;
        DROP TABLE course_versions;
        """
    )
