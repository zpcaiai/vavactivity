"""Create the production operations control plane.

Revision ID: 20260806_0083
Revises: 20260805_0082

Module: system
Risk: low
Estimated lock: under 5 seconds on an empty system table set
Backfill: no
Rollback: forward-fix preferred after production use
"""

# ruff: noqa: E501

from alembic import op

revision = "20260806_0083"
down_revision = "20260805_0082"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(
        """
        CREATE TABLE system_feature_flags (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          flag_code VARCHAR(128) NOT NULL UNIQUE,
          status VARCHAR(32) NOT NULL DEFAULT 'draft',
          targeting_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
          default_value JSONB NOT NULL,
          description TEXT,
          version INTEGER NOT NULL DEFAULT 1,
          created_by UUID NOT NULL REFERENCES users(id),
          approved_by UUID REFERENCES users(id),
          activated_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (status IN ('draft','approved','active','disabled')),
          CHECK (approved_by IS NULL OR approved_by <> created_by)
        );

        CREATE TABLE system_release_records (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          release_version VARCHAR(64) NOT NULL UNIQUE,
          git_commit VARCHAR(64) NOT NULL,
          status VARCHAR(32) NOT NULL,
          image_digests JSONB NOT NULL,
          database_revision VARCHAR(64) NOT NULL,
          contract_checksums JSONB NOT NULL,
          configuration_fingerprint JSONB NOT NULL,
          evidence_manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_by UUID NOT NULL REFERENCES users(id),
          approved_by UUID REFERENCES users(id),
          deployed_at TIMESTAMPTZ,
          rolled_back_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (status IN ('candidate','staging','approved','active','failed','rolled_back')),
          CHECK (approved_by IS NULL OR approved_by <> created_by)
        );
        CREATE INDEX ix_system_releases_status_created
          ON system_release_records(status, created_at DESC);

        CREATE TABLE system_maintenance_states (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          environment VARCHAR(32) NOT NULL UNIQUE,
          status VARCHAR(32) NOT NULL DEFAULT 'disabled',
          write_scope JSONB NOT NULL DEFAULT '{}'::jsonb,
          public_message TEXT,
          reason_code VARCHAR(128),
          changed_by UUID NOT NULL REFERENCES users(id),
          approved_by UUID REFERENCES users(id),
          enabled_at TIMESTAMPTZ,
          disabled_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (status IN ('disabled','enabled')),
          CHECK (approved_by IS NULL OR approved_by <> changed_by)
        );

        CREATE TABLE system_backfill_jobs (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          job_code VARCHAR(128) NOT NULL,
          release_version VARCHAR(64) NOT NULL,
          status VARCHAR(32) NOT NULL DEFAULT 'pending',
          cursor_snapshot JSONB,
          processed_count BIGINT NOT NULL DEFAULT 0,
          failed_count BIGINT NOT NULL DEFAULT 0,
          rate_limit_per_second INTEGER NOT NULL DEFAULT 50,
          idempotency_namespace VARCHAR(128) NOT NULL,
          started_at TIMESTAMPTZ,
          completed_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(job_code, release_version),
          CHECK (status IN ('pending','running','paused','completed','failed','cancelled')),
          CHECK (processed_count >= 0 AND failed_count >= 0),
          CHECK (rate_limit_per_second > 0)
        );
        CREATE INDEX ix_system_backfills_status_created
          ON system_backfill_jobs(status, created_at);

        CREATE TABLE system_backup_records (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          backup_type VARCHAR(64) NOT NULL,
          environment VARCHAR(32) NOT NULL,
          status VARCHAR(32) NOT NULL,
          started_at TIMESTAMPTZ NOT NULL,
          completed_at TIMESTAMPTZ,
          backup_reference_encrypted TEXT,
          checksum_manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
          source_release_version VARCHAR(64),
          source_database_revision VARCHAR(64),
          verified_at TIMESTAMPTZ,
          expires_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (backup_type IN ('postgres_full','postgres_wal','object_storage','configuration','complete')),
          CHECK (status IN ('started','completed','failed','verified','expired'))
        );
        CREATE INDEX ix_system_backups_environment_created
          ON system_backup_records(environment, created_at DESC);

        CREATE TABLE system_restore_drills (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          drill_code VARCHAR(128) NOT NULL UNIQUE,
          environment VARCHAR(32) NOT NULL,
          backup_record_id UUID REFERENCES system_backup_records(id),
          status VARCHAR(32) NOT NULL,
          target_release_version VARCHAR(64),
          target_database_revision VARCHAR(64),
          verification_manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
          failure_summary TEXT,
          started_at TIMESTAMPTZ NOT NULL,
          completed_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (status IN ('started','passed','failed','cancelled'))
        );
        CREATE INDEX ix_system_restore_drills_status_started
          ON system_restore_drills(status, started_at DESC);

        CREATE TABLE system_capacity_baselines (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          release_version VARCHAR(64) NOT NULL,
          environment VARCHAR(32) NOT NULL,
          scenario_code VARCHAR(128) NOT NULL,
          infrastructure_snapshot JSONB NOT NULL,
          load_snapshot JSONB NOT NULL,
          result_metrics JSONB NOT NULL,
          status VARCHAR(32) NOT NULL,
          tested_at TIMESTAMPTZ NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(release_version, environment, scenario_code),
          CHECK (status IN ('passed','failed','not_certified'))
        );
        """
    )


def downgrade() -> None:
    _run(
        """
        DROP TABLE system_capacity_baselines;
        DROP TABLE system_restore_drills;
        DROP TABLE system_backup_records;
        DROP TABLE system_backfill_jobs;
        DROP TABLE system_maintenance_states;
        DROP TABLE system_release_records;
        DROP TABLE system_feature_flags;
        """
    )
