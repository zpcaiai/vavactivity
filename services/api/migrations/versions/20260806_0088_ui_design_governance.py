"""Create the Batch 22 UI design governance control plane.

Revision ID: 20260806_0088
Revises: 20260806_0087
"""

from alembic import op

revision = "20260806_0088"
down_revision = "20260806_0087"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(
        """
        CREATE TABLE ui_token_releases (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          token_version VARCHAR(64) NOT NULL UNIQUE,
          manifest_checksum_sha256 VARCHAR(64) NOT NULL,
          generated_checksum_sha256 VARCHAR(64) NOT NULL,
          change_summary TEXT NOT NULL,
          breaking_changes JSONB NOT NULL DEFAULT '[]'::jsonb,
          evidence_manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
          status VARCHAR(32) NOT NULL DEFAULT 'draft',
          created_by UUID NOT NULL REFERENCES users(id),
          approved_by UUID REFERENCES users(id),
          released_by UUID REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          approved_at TIMESTAMPTZ,
          released_at TIMESTAMPTZ,
          CHECK (manifest_checksum_sha256 ~ '^[0-9a-f]{64}$'),
          CHECK (generated_checksum_sha256 ~ '^[0-9a-f]{64}$'),
          CHECK (status IN ('draft','approved','released','rejected','superseded')),
          CHECK (approved_by IS NULL OR approved_by<>created_by),
          CHECK (released_by IS NULL OR released_by<>created_by)
        );

        CREATE TABLE ui_components (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          component_code VARCHAR(128) NOT NULL UNIQUE,
          package_name VARCHAR(255) NOT NULL,
          source_location VARCHAR(1000) NOT NULL,
          owner_team VARCHAR(128) NOT NULL,
          accessibility_contract JSONB NOT NULL,
          supported_states JSONB NOT NULL,
          status VARCHAR(32) NOT NULL DEFAULT 'active',
          replacement_component_code VARCHAR(128),
          deprecation_reason TEXT,
          created_by UUID NOT NULL REFERENCES users(id),
          updated_by UUID NOT NULL REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (status IN ('active','experimental','deprecated','retired'))
        );

        CREATE TABLE ui_patterns (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          pattern_code VARCHAR(128) NOT NULL UNIQUE,
          name VARCHAR(300) NOT NULL,
          audience VARCHAR(32) NOT NULL,
          source_location VARCHAR(1000) NOT NULL,
          required_components JSONB NOT NULL,
          required_states JSONB NOT NULL,
          accessibility_notes TEXT NOT NULL,
          status VARCHAR(32) NOT NULL DEFAULT 'active',
          created_by UUID NOT NULL REFERENCES users(id),
          updated_by UUID NOT NULL REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (audience IN ('user','admin','shared')),
          CHECK (status IN ('active','experimental','deprecated','retired'))
        );

        CREATE TABLE ui_audit_runs (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          audit_code VARCHAR(128) NOT NULL UNIQUE,
          audit_type VARCHAR(32) NOT NULL,
          application_code VARCHAR(64) NOT NULL,
          route_path VARCHAR(500),
          git_commit VARCHAR(64) NOT NULL,
          environment VARCHAR(32) NOT NULL,
          viewport VARCHAR(64),
          theme VARCHAR(32),
          locale VARCHAR(32),
          density VARCHAR(32),
          status VARCHAR(32) NOT NULL,
          findings JSONB NOT NULL DEFAULT '[]'::jsonb,
          metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
          artifact_reference VARCHAR(2000),
          evidence_checksum_sha256 VARCHAR(64),
          manual_review_required BOOLEAN NOT NULL DEFAULT false,
          ran_by UUID NOT NULL REFERENCES users(id),
          reviewed_by UUID REFERENCES users(id),
          started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          completed_at TIMESTAMPTZ,
          reviewed_at TIMESTAMPTZ,
          CHECK (audit_type IN ('accessibility','responsive','visual','page','storybook')),
          CHECK (
            status IN ('not_run','running','technical_pass','needs_review','approved','failed')
          ),
          CHECK (reviewed_by IS NULL OR reviewed_by<>ran_by)
        );

        CREATE TABLE ui_visual_baselines (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          baseline_code VARCHAR(255) NOT NULL,
          application_code VARCHAR(64) NOT NULL,
          route_path VARCHAR(500) NOT NULL,
          viewport VARCHAR(64) NOT NULL,
          theme VARCHAR(32) NOT NULL,
          locale VARCHAR(32) NOT NULL,
          density VARCHAR(32) NOT NULL,
          artifact_reference VARCHAR(2000) NOT NULL,
          checksum_sha256 VARCHAR(64) NOT NULL,
          status VARCHAR(32) NOT NULL DEFAULT 'pending',
          created_by UUID NOT NULL REFERENCES users(id),
          approved_by UUID REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          approved_at TIMESTAMPTZ,
          superseded_at TIMESTAMPTZ,
          UNIQUE(baseline_code,checksum_sha256),
          CHECK (checksum_sha256 ~ '^[0-9a-f]{64}$'),
          CHECK (status IN ('pending','approved','rejected','superseded')),
          CHECK (approved_by IS NULL OR approved_by<>created_by)
        );

        CREATE TABLE ui_visual_differences (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          audit_run_id UUID NOT NULL REFERENCES ui_audit_runs(id) ON DELETE CASCADE,
          baseline_id UUID REFERENCES ui_visual_baselines(id),
          case_code VARCHAR(255) NOT NULL,
          difference_ratio NUMERIC(9,8) NOT NULL,
          threshold_ratio NUMERIC(9,8) NOT NULL,
          changed_regions JSONB NOT NULL DEFAULT '[]'::jsonb,
          diff_artifact_reference VARCHAR(2000),
          status VARCHAR(32) NOT NULL DEFAULT 'pending',
          reviewed_by UUID REFERENCES users(id),
          reviewed_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(audit_run_id,case_code),
          CHECK (difference_ratio>=0 AND difference_ratio<=1),
          CHECK (threshold_ratio>=0 AND threshold_ratio<=1),
          CHECK (status IN ('pending','accepted','rejected'))
        );

        CREATE INDEX ix_ui_audit_runs_type_status ON ui_audit_runs(audit_type,status);
        CREATE INDEX ix_ui_audit_runs_route ON ui_audit_runs(application_code,route_path);
        CREATE INDEX ix_ui_baselines_case
          ON ui_visual_baselines(application_code,route_path,status);
        CREATE INDEX ix_ui_differences_status ON ui_visual_differences(status);
        """
    )


def downgrade() -> None:
    _run(
        """
        DROP TABLE ui_visual_differences;
        DROP TABLE ui_visual_baselines;
        DROP TABLE ui_audit_runs;
        DROP TABLE ui_patterns;
        DROP TABLE ui_components;
        DROP TABLE ui_token_releases;
        """
    )
