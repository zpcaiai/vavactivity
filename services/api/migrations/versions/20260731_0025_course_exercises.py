"""Create course exercise and assessment tables.

Revision ID: 20260731_0025
Revises: 20260731_0024
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260731_0025"
down_revision: str | None = "20260731_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _run(sql: str) -> None:
    for statement in sql.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(
        """
        CREATE TABLE course_exercises (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          lesson_id UUID NOT NULL REFERENCES course_lessons(id) ON DELETE CASCADE,
          exercise_code VARCHAR(128) NOT NULL,
          exercise_type VARCHAR(32) NOT NULL,
          status VARCHAR(32) NOT NULL DEFAULT 'draft',
          grading_mode VARCHAR(32) NOT NULL,
          passing_score_basis_points INTEGER
            CHECK (passing_score_basis_points BETWEEN 0 AND 10000),
          maximum_attempts INTEGER CHECK (maximum_attempts IS NULL OR maximum_attempts > 0),
          cooldown_minutes INTEGER CHECK (cooldown_minutes IS NULL OR cooldown_minutes >= 0),
          randomize_questions BOOLEAN NOT NULL DEFAULT FALSE,
          randomize_options BOOLEAN NOT NULL DEFAULT FALSE,
          reveal_answers_policy VARCHAR(32) NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(lesson_id, exercise_code)
        );
        CREATE TABLE exercise_questions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          exercise_id UUID NOT NULL REFERENCES course_exercises(id) ON DELETE CASCADE,
          question_type VARCHAR(32) NOT NULL,
          sort_order INTEGER NOT NULL,
          points INTEGER NOT NULL DEFAULT 1 CHECK (points > 0),
          required BOOLEAN NOT NULL DEFAULT TRUE,
          question_schema JSONB NOT NULL,
          answer_key_encrypted TEXT,
          grading_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE exercise_question_localizations (
          question_id UUID NOT NULL REFERENCES exercise_questions(id) ON DELETE CASCADE,
          locale VARCHAR(16) NOT NULL,
          prompt_blocks JSONB NOT NULL,
          options JSONB NOT NULL DEFAULT '[]'::jsonb,
          explanation_blocks JSONB NOT NULL DEFAULT '[]'::jsonb,
          PRIMARY KEY(question_id, locale)
        );
        CREATE TABLE exercise_attempts (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          exercise_id UUID NOT NULL REFERENCES course_exercises(id),
          enrollment_id UUID NOT NULL REFERENCES course_enrollments(id),
          user_id UUID NOT NULL REFERENCES users(id),
          attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
          status VARCHAR(32) NOT NULL,
          question_snapshot JSONB NOT NULL,
          response_snapshot_encrypted TEXT NOT NULL,
          auto_score_basis_points INTEGER CHECK (auto_score_basis_points BETWEEN 0 AND 10000),
          manual_score_basis_points INTEGER CHECK (manual_score_basis_points BETWEEN 0 AND 10000),
          final_score_basis_points INTEGER CHECK (final_score_basis_points BETWEEN 0 AND 10000),
          passed BOOLEAN,
          submitted_at TIMESTAMPTZ,
          graded_at TIMESTAMPTZ,
          graded_by UUID REFERENCES users(id),
          grader_feedback_encrypted TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(exercise_id, enrollment_id, attempt_number)
        );
        CREATE INDEX ix_exercise_attempts_grading
          ON exercise_attempts(status, submitted_at);
        """
    )


def downgrade() -> None:
    _run(
        """
        DROP TABLE exercise_attempts;
        DROP TABLE exercise_question_localizations;
        DROP TABLE exercise_questions;
        DROP TABLE course_exercises;
        """
    )
