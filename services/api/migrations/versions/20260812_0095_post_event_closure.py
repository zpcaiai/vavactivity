# ruff: noqa: E501

"""Create post-event closure schema: candidate freeze, survey and result letters.

Covers MUT-001, MUT-002, SUR-001, SUR-002 and RES-001.

Revision ID: 20260812_0095
Revises: 20260808_0094
"""

from alembic import op

revision = "20260812_0095"
down_revision = "20260808_0094"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(
        """
        CREATE TABLE activity_candidate_snapshots (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          activity_id UUID NOT NULL REFERENCES activities(id),
          snapshot_version INTEGER NOT NULL,
          status VARCHAR(24) NOT NULL DEFAULT 'draft',
          cutoff_at TIMESTAMPTZ NOT NULL,
          frozen_at TIMESTAMPTZ,
          frozen_by UUID REFERENCES users(id),
          superseded_at TIMESTAMPTZ,
          superseded_by_snapshot_id UUID,
          considered_count INTEGER NOT NULL DEFAULT 0,
          eligible_count INTEGER NOT NULL DEFAULT 0,
          excluded_count INTEGER NOT NULL DEFAULT 0,
          freeze_note TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (activity_id, snapshot_version),
          CHECK (snapshot_version >= 1),
          CHECK (status IN ('draft','frozen','superseded')),
          CHECK (status <> 'frozen' OR frozen_at IS NOT NULL)
        );
        CREATE UNIQUE INDEX activity_candidate_snapshots_one_active
          ON activity_candidate_snapshots (activity_id) WHERE status = 'frozen';
        CREATE INDEX activity_candidate_snapshots_activity_idx
          ON activity_candidate_snapshots (activity_id, status);

        CREATE TABLE activity_candidate_entries (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          snapshot_id UUID NOT NULL REFERENCES activity_candidate_snapshots(id) ON DELETE CASCADE,
          activity_id UUID NOT NULL REFERENCES activities(id),
          user_id UUID NOT NULL REFERENCES users(id),
          registration_id UUID NOT NULL REFERENCES activity_registrations(id),
          gender VARCHAR(32),
          group_id UUID,
          display_name VARCHAR(160) NOT NULL,
          eligibility VARCHAR(16) NOT NULL,
          exclusion_kind VARCHAR(32),
          exclusion_reason TEXT,
          excluded_by UUID REFERENCES users(id),
          excluded_at TIMESTAMPTZ,
          checked_in_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (snapshot_id, user_id),
          CHECK (eligibility IN ('eligible','excluded')),
          CHECK (exclusion_kind IS NULL OR exclusion_kind IN ('not_checked_in','no_show','cancelled','manual','restricted','staff')),
          CHECK (eligibility = 'eligible' OR exclusion_kind IS NOT NULL),
          CHECK (eligibility = 'excluded' OR exclusion_kind IS NULL),
          CHECK (exclusion_kind <> 'manual' OR (exclusion_reason IS NOT NULL AND excluded_by IS NOT NULL))
        );
        CREATE INDEX activity_candidate_entries_eligible_idx
          ON activity_candidate_entries (snapshot_id, eligibility);
        CREATE INDEX activity_candidate_entries_user_idx
          ON activity_candidate_entries (user_id, activity_id);

        CREATE TABLE activity_selection_policies (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          activity_id UUID NOT NULL REFERENCES activities(id),
          visibility_mode VARCHAR(32) NOT NULL DEFAULT 'opposite_gender',
          max_selections INTEGER NOT NULL DEFAULT 3,
          min_selections INTEGER NOT NULL DEFAULT 0,
          edit_window_hours INTEGER NOT NULL DEFAULT 24,
          allow_edit_after_submit BOOLEAN NOT NULL DEFAULT true,
          custom_rule JSONB NOT NULL DEFAULT '{}'::jsonb,
          updated_by UUID REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (activity_id),
          CHECK (visibility_mode IN ('opposite_gender','same_gender','all_genders','custom')),
          CHECK (max_selections BETWEEN 1 AND 3),
          CHECK (min_selections BETWEEN 0 AND max_selections),
          CHECK (edit_window_hours BETWEEN 0 AND 720)
        );

        CREATE TABLE activity_pass_reason_options (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          activity_id UUID REFERENCES activities(id),
          reason_code VARCHAR(64) NOT NULL,
          sort_order INTEGER NOT NULL DEFAULT 0,
          requires_note BOOLEAN NOT NULL DEFAULT false,
          is_active BOOLEAN NOT NULL DEFAULT true,
          created_by UUID REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (reason_code ~ '^[a-z][a-z0-9_]{1,63}$')
        );
        CREATE UNIQUE INDEX activity_pass_reason_options_scoped
          ON activity_pass_reason_options (activity_id, reason_code) WHERE activity_id IS NOT NULL;
        CREATE UNIQUE INDEX activity_pass_reason_options_global
          ON activity_pass_reason_options (reason_code) WHERE activity_id IS NULL;

        CREATE TABLE activity_selection_submissions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          snapshot_id UUID NOT NULL REFERENCES activity_candidate_snapshots(id),
          activity_id UUID NOT NULL REFERENCES activities(id),
          chooser_user_id UUID NOT NULL REFERENCES users(id),
          status VARCHAR(16) NOT NULL DEFAULT 'draft',
          selection_count INTEGER NOT NULL DEFAULT 0,
          no_selection_reason_code VARCHAR(64),
          no_selection_reason_note TEXT,
          submitted_at TIMESTAMPTZ,
          editable_until TIMESTAMPTZ,
          version INTEGER NOT NULL DEFAULT 1,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (snapshot_id, chooser_user_id),
          CHECK (status IN ('draft','submitted','withdrawn')),
          CHECK (selection_count BETWEEN 0 AND 3),
          CHECK (status <> 'submitted' OR submitted_at IS NOT NULL),
          CHECK (status <> 'submitted' OR selection_count > 0 OR no_selection_reason_code IS NOT NULL),
          CHECK (selection_count = 0 OR no_selection_reason_code IS NULL)
        );
        CREATE INDEX activity_selection_submissions_chooser_idx
          ON activity_selection_submissions (chooser_user_id, activity_id);

        CREATE TABLE activity_selection_items (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          submission_id UUID NOT NULL REFERENCES activity_selection_submissions(id) ON DELETE CASCADE,
          chosen_user_id UUID NOT NULL REFERENCES users(id),
          rank INTEGER NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (submission_id, chosen_user_id),
          UNIQUE (submission_id, rank),
          CHECK (rank BETWEEN 1 AND 3)
        );
        CREATE INDEX activity_selection_items_chosen_idx
          ON activity_selection_items (chosen_user_id);

        CREATE TABLE activity_selection_audits (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          activity_id UUID NOT NULL REFERENCES activities(id),
          snapshot_id UUID,
          actor_id UUID REFERENCES users(id),
          actor_kind VARCHAR(16) NOT NULL,
          action VARCHAR(64) NOT NULL,
          subject_user_id UUID,
          reason TEXT,
          metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (actor_kind IN ('member','staff','admin','system'))
        );
        CREATE INDEX activity_selection_audits_activity_idx
          ON activity_selection_audits (activity_id, created_at DESC);
        """
    )

    _run(
        """
        CREATE TABLE survey_definitions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          survey_code VARCHAR(128) NOT NULL,
          semantic_version VARCHAR(32) NOT NULL,
          scope VARCHAR(32) NOT NULL DEFAULT 'post_event',
          title VARCHAR(300) NOT NULL,
          description TEXT,
          default_locale VARCHAR(16) NOT NULL DEFAULT 'zh-CN',
          status VARCHAR(16) NOT NULL DEFAULT 'draft',
          published_at TIMESTAMPTZ,
          published_by UUID REFERENCES users(id),
          created_by UUID REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (survey_code, semantic_version),
          CHECK (status IN ('draft','published','archived')),
          CHECK (status <> 'published' OR published_at IS NOT NULL)
        );

        CREATE TABLE survey_questions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          definition_id UUID NOT NULL REFERENCES survey_definitions(id) ON DELETE CASCADE,
          question_code VARCHAR(64) NOT NULL,
          question_type VARCHAR(32) NOT NULL,
          prompt TEXT NOT NULL,
          help_text TEXT,
          is_required BOOLEAN NOT NULL DEFAULT true,
          per_subject BOOLEAN NOT NULL DEFAULT false,
          position INTEGER NOT NULL,
          config JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (definition_id, question_code),
          UNIQUE (definition_id, position),
          CHECK (position >= 1),
          CHECK (question_type IN ('rating','segment_rating','single_choice','multi_choice','open_text','boolean'))
        );

        CREATE TABLE survey_question_localizations (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          question_id UUID NOT NULL REFERENCES survey_questions(id) ON DELETE CASCADE,
          locale VARCHAR(16) NOT NULL,
          prompt TEXT NOT NULL,
          help_text TEXT,
          options JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (question_id, locale)
        );

        CREATE TABLE activity_survey_assignments (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          activity_id UUID NOT NULL REFERENCES activities(id),
          definition_id UUID NOT NULL REFERENCES survey_definitions(id),
          snapshot_id UUID REFERENCES activity_candidate_snapshots(id),
          status VARCHAR(16) NOT NULL DEFAULT 'scheduled',
          opens_at TIMESTAMPTZ,
          deadline_at TIMESTAMPTZ NOT NULL,
          display_timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai',
          reminder_offsets_hours JSONB NOT NULL DEFAULT '[48, 12]'::jsonb,
          created_by UUID REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (activity_id, definition_id),
          CHECK (status IN ('scheduled','open','closed')),
          CHECK (opens_at IS NULL OR opens_at < deadline_at)
        );

        CREATE TABLE survey_tasks (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          assignment_id UUID NOT NULL REFERENCES activity_survey_assignments(id),
          activity_id UUID NOT NULL REFERENCES activities(id),
          user_id UUID NOT NULL REFERENCES users(id),
          status VARCHAR(16) NOT NULL DEFAULT 'pending',
          due_at TIMESTAMPTZ NOT NULL,
          completed_at TIMESTAMPTZ,
          reminder_count INTEGER NOT NULL DEFAULT 0,
          last_reminder_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (assignment_id, user_id),
          CHECK (status IN ('pending','in_progress','completed','expired','waived')),
          CHECK (status <> 'completed' OR completed_at IS NOT NULL)
        );
        CREATE INDEX survey_tasks_user_status_idx ON survey_tasks (user_id, status, due_at);

        CREATE TABLE survey_responses (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          assignment_id UUID NOT NULL REFERENCES activity_survey_assignments(id),
          definition_id UUID NOT NULL REFERENCES survey_definitions(id),
          user_id UUID NOT NULL REFERENCES users(id),
          status VARCHAR(16) NOT NULL DEFAULT 'draft',
          submitted_at TIMESTAMPTZ,
          last_edited_at TIMESTAMPTZ,
          edit_count INTEGER NOT NULL DEFAULT 0,
          override_by UUID REFERENCES users(id),
          override_reason TEXT,
          version INTEGER NOT NULL DEFAULT 1,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (assignment_id, user_id),
          CHECK (status IN ('draft','submitted')),
          CHECK (status <> 'submitted' OR submitted_at IS NOT NULL),
          CHECK (override_by IS NULL OR override_reason IS NOT NULL)
        );

        CREATE TABLE survey_answers (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          response_id UUID NOT NULL REFERENCES survey_responses(id) ON DELETE CASCADE,
          question_id UUID NOT NULL REFERENCES survey_questions(id),
          subject_user_id UUID,
          subject_key VARCHAR(64) NOT NULL DEFAULT '-',
          rating_value INTEGER,
          boolean_value BOOLEAN,
          choice_values JSONB NOT NULL DEFAULT '[]'::jsonb,
          text_value_encrypted TEXT,
          answered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (response_id, question_id, subject_key),
          CHECK (subject_user_id IS NULL OR subject_key = subject_user_id::text),
          CHECK (subject_user_id IS NOT NULL OR subject_key = '-'),
          CHECK (rating_value IS NULL OR rating_value BETWEEN 1 AND 10)
        );

        CREATE TABLE survey_reminder_dispatches (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          task_id UUID NOT NULL REFERENCES survey_tasks(id) ON DELETE CASCADE,
          reminder_code VARCHAR(32) NOT NULL,
          dedupe_key VARCHAR(255) NOT NULL,
          scheduled_for TIMESTAMPTZ NOT NULL,
          dispatched_at TIMESTAMPTZ,
          status VARCHAR(16) NOT NULL DEFAULT 'scheduled',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (dedupe_key),
          CHECK (status IN ('scheduled','sent','suppressed','failed'))
        );
        """
    )

    _run(
        """
        CREATE TABLE result_letter_templates (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          template_code VARCHAR(128) NOT NULL,
          semantic_version VARCHAR(32) NOT NULL,
          locale VARCHAR(16) NOT NULL,
          outcome VARCHAR(32) NOT NULL,
          subject_template TEXT NOT NULL,
          body_template TEXT NOT NULL,
          declared_variables JSONB NOT NULL DEFAULT '[]'::jsonb,
          status VARCHAR(16) NOT NULL DEFAULT 'draft',
          published_at TIMESTAMPTZ,
          published_by UUID REFERENCES users(id),
          created_by UUID REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (template_code, semantic_version, locale),
          CHECK (status IN ('draft','published','archived')),
          CHECK (outcome IN ('mutual_match','no_match','not_eligible'))
        );

        CREATE TABLE result_letters (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          activity_id UUID NOT NULL REFERENCES activities(id),
          snapshot_id UUID NOT NULL REFERENCES activity_candidate_snapshots(id),
          recipient_user_id UUID NOT NULL REFERENCES users(id),
          template_id UUID REFERENCES result_letter_templates(id),
          outcome VARCHAR(32) NOT NULL,
          status VARCHAR(24) NOT NULL DEFAULT 'draft',
          version INTEGER NOT NULL DEFAULT 1,
          subject_encrypted TEXT NOT NULL,
          body_encrypted TEXT NOT NULL,
          content_hash VARCHAR(64) NOT NULL,
          matched_user_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
          authored_by UUID REFERENCES users(id),
          generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          published_at TIMESTAMPTZ,
          published_by UUID REFERENCES users(id),
          revoked_at TIMESTAMPTZ,
          revoked_by UUID REFERENCES users(id),
          revoked_reason TEXT,
          read_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (activity_id, recipient_user_id, version),
          CHECK (version >= 1),
          CHECK (outcome IN ('mutual_match','no_match','not_eligible')),
          CHECK (status IN ('draft','pending_review','approved','rejected','published','revoked')),
          CHECK (status <> 'published' OR (published_at IS NOT NULL AND published_by IS NOT NULL)),
          CHECK (status <> 'revoked' OR revoked_reason IS NOT NULL)
        );
        CREATE INDEX result_letters_recipient_idx
          ON result_letters (recipient_user_id, status, published_at DESC);
        CREATE INDEX result_letters_review_queue_idx
          ON result_letters (status, activity_id) WHERE status IN ('pending_review','approved');

        CREATE TABLE result_letter_reviews (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          letter_id UUID NOT NULL REFERENCES result_letters(id) ON DELETE CASCADE,
          reviewer_id UUID NOT NULL REFERENCES users(id),
          decision VARCHAR(24) NOT NULL,
          comment TEXT,
          reviewed_content_hash VARCHAR(64) NOT NULL,
          decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (decision IN ('approved','rejected','changes_requested')),
          CHECK (decision = 'approved' OR comment IS NOT NULL)
        );
        CREATE INDEX result_letter_reviews_letter_idx
          ON result_letter_reviews (letter_id, decided_at DESC);

        CREATE TABLE result_letter_releases (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          letter_id UUID NOT NULL REFERENCES result_letters(id),
          version INTEGER NOT NULL,
          subject_encrypted TEXT NOT NULL,
          body_encrypted TEXT NOT NULL,
          content_hash VARCHAR(64) NOT NULL,
          approved_by UUID REFERENCES users(id),
          released_by UUID REFERENCES users(id),
          released_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          notification_dedupe_key VARCHAR(255),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (letter_id, version)
        );
        """
    )

    # A released letter is evidence. Blocking UPDATE/DELETE in the database makes
    # "published content cannot silently change" a storage guarantee rather than
    # an application convention.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION result_letter_releases_immutable()
        RETURNS TRIGGER AS $$
        BEGIN
          RAISE EXCEPTION 'result_letter_releases rows are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER result_letter_releases_no_mutation
        BEFORE UPDATE OR DELETE ON result_letter_releases
        FOR EACH ROW EXECUTE FUNCTION result_letter_releases_immutable();
        """
    )

    # Permission rows are owned by ``vav.modules.identity.permissions`` and
    # materialized by ``seed_permissions``; inserting them here as well would
    # duplicate that source of truth. The codes added in this batch are:
    #   activities.candidates.freeze / .exclude
    #   activities.selection_policy.manage
    #   surveys.definitions.manage / assignments.manage
    #   surveys.responses.read_aggregate / .override
    #   result_letters.generate / .review / .publish / .revoke


def downgrade() -> None:
    _run(
        """
        DROP TRIGGER IF EXISTS result_letter_releases_no_mutation ON result_letter_releases;
        DROP FUNCTION IF EXISTS result_letter_releases_immutable();
        DROP TABLE IF EXISTS result_letter_releases;
        DROP TABLE IF EXISTS result_letter_reviews;
        DROP TABLE IF EXISTS result_letters;
        DROP TABLE IF EXISTS result_letter_templates;
        DROP TABLE IF EXISTS survey_reminder_dispatches;
        DROP TABLE IF EXISTS survey_answers;
        DROP TABLE IF EXISTS survey_responses;
        DROP TABLE IF EXISTS survey_tasks;
        DROP TABLE IF EXISTS activity_survey_assignments;
        DROP TABLE IF EXISTS survey_question_localizations;
        DROP TABLE IF EXISTS survey_questions;
        DROP TABLE IF EXISTS survey_definitions;
        DROP TABLE IF EXISTS activity_selection_audits;
        DROP TABLE IF EXISTS activity_selection_items;
        DROP TABLE IF EXISTS activity_selection_submissions;
        DROP TABLE IF EXISTS activity_pass_reason_options;
        DROP TABLE IF EXISTS activity_selection_policies;
        DROP TABLE IF EXISTS activity_candidate_entries;
        DROP TABLE IF EXISTS activity_candidate_snapshots;
        """
    )
