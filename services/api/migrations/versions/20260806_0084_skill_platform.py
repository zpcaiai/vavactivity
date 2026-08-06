"""Create the governed Skill registry, runtime and Marketplace control plane.

Revision ID: 20260806_0084
Revises: 20260806_0083

Module: skills_platform
Risk: medium
Estimated lock: under 10 seconds for new tables
Backfill: no
Rollback: allowed before production installations exist
"""

# ruff: noqa: E501

from alembic import op

revision = "20260806_0084"
down_revision = "20260806_0083"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(
        """
        CREATE TABLE skill_publishers (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          publisher_code VARCHAR(128) NOT NULL UNIQUE,
          display_name VARCHAR(300) NOT NULL,
          publisher_type VARCHAR(32) NOT NULL,
          verification_status VARCHAR(32) NOT NULL DEFAULT 'pending',
          organization_reference_id UUID,
          signing_key_manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
          status VARCHAR(32) NOT NULL DEFAULT 'active',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          verified_at TIMESTAMPTZ,
          suspended_at TIMESTAMPTZ,
          CHECK (publisher_type IN ('official','organization','verified_partner','community')),
          CHECK (verification_status IN ('pending','verified','rejected','suspended')),
          CHECK (status IN ('active','suspended','revoked'))
        );

        CREATE TABLE registered_skills (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          skill_name VARCHAR(255) NOT NULL UNIQUE,
          publisher_id UUID NOT NULL REFERENCES skill_publishers(id),
          display_name VARCHAR(300) NOT NULL,
          description TEXT,
          skill_type VARCHAR(32) NOT NULL,
          visibility VARCHAR(32) NOT NULL,
          trust_level VARCHAR(32) NOT NULL,
          lifecycle_status VARCHAR(32) NOT NULL DEFAULT 'active',
          current_stable_version_id UUID,
          latest_version_id UUID,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (visibility IN ('builtin','organization_private','marketplace_unlisted','marketplace_public')),
          CHECK (trust_level IN ('builtin_trusted','official_signed','verified_publisher','community_reviewed','unverified','quarantined','revoked')),
          CHECK (lifecycle_status IN ('active','deprecated','disabled_new_installs','quarantined','revoked'))
        );

        CREATE TABLE registered_skill_versions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          registered_skill_id UUID NOT NULL REFERENCES registered_skills(id),
          semantic_version VARCHAR(64) NOT NULL,
          manifest_version VARCHAR(32) NOT NULL,
          runtime_api_version VARCHAR(32) NOT NULL,
          manifest JSONB NOT NULL,
          manifest_checksum VARCHAR(128) NOT NULL,
          package_reference_encrypted TEXT NOT NULL,
          package_checksum VARCHAR(128) NOT NULL,
          sbom_reference_encrypted TEXT,
          provenance_reference_encrypted TEXT,
          signature_status VARCHAR(32) NOT NULL,
          security_status VARCHAR(32) NOT NULL,
          review_status VARCHAR(32) NOT NULL,
          compatibility_status VARCHAR(32) NOT NULL,
          published_at TIMESTAMPTZ,
          deprecated_at TIMESTAMPTZ,
          revoked_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(registered_skill_id, semantic_version),
          CHECK (signature_status IN ('pending','verified','failed','revoked')),
          CHECK (security_status IN ('pending','passed','passed_with_warnings','failed','quarantined','revoked')),
          CHECK (review_status IN ('draft','automated_review','human_review','approved','rejected')),
          CHECK (compatibility_status IN ('pending','compatible','incompatible'))
        );
        ALTER TABLE registered_skills ADD CONSTRAINT fk_registered_skills_stable_version FOREIGN KEY (current_stable_version_id) REFERENCES registered_skill_versions(id);
        ALTER TABLE registered_skills ADD CONSTRAINT fk_registered_skills_latest_version FOREIGN KEY (latest_version_id) REFERENCES registered_skill_versions(id);
        CREATE INDEX ix_registered_skill_versions_skill_created ON registered_skill_versions(registered_skill_id, created_at DESC);

        CREATE TABLE skill_dependencies (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          skill_version_id UUID NOT NULL REFERENCES registered_skill_versions(id) ON DELETE CASCADE,
          dependency_type VARCHAR(32) NOT NULL,
          dependency_name VARCHAR(255) NOT NULL,
          version_constraint VARCHAR(128),
          optional BOOLEAN NOT NULL DEFAULT false,
          peer BOOLEAN NOT NULL DEFAULT false,
          resolution_status VARCHAR(32) NOT NULL DEFAULT 'pending',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(skill_version_id, dependency_type, dependency_name),
          CHECK (dependency_type IN ('skill','module','capability','provider','runtime','platform')),
          CHECK (resolution_status IN ('pending','resolved','missing','conflict','revoked'))
        );

        CREATE TABLE skill_compatibility_records (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          skill_version_id UUID NOT NULL REFERENCES registered_skill_versions(id) ON DELETE CASCADE,
          platform_version_range VARCHAR(128) NOT NULL,
          runtime_api_version_range VARCHAR(128) NOT NULL,
          compatible BOOLEAN NOT NULL,
          test_report JSONB NOT NULL,
          verified_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE skill_installations (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          registered_skill_id UUID NOT NULL REFERENCES registered_skills(id),
          installed_version_id UUID NOT NULL REFERENCES registered_skill_versions(id),
          environment VARCHAR(32) NOT NULL,
          status VARCHAR(32) NOT NULL DEFAULT 'draft',
          configuration_encrypted JSONB NOT NULL DEFAULT '{}'::jsonb,
          configuration_version INTEGER NOT NULL DEFAULT 1,
          granted_permissions JSONB NOT NULL DEFAULT '[]'::jsonb,
          granted_capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
          installed_by UUID NOT NULL REFERENCES users(id),
          approved_by UUID REFERENCES users(id),
          installed_at TIMESTAMPTZ,
          activated_at TIMESTAMPTZ,
          disabled_at TIMESTAMPTZ,
          previous_version_id UUID REFERENCES registered_skill_versions(id),
          version INTEGER NOT NULL DEFAULT 1,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(registered_skill_id, environment),
          CHECK (status IN ('draft','planning','approval_required','installing','validating','active','disabled','upgrade_pending','rollback_pending','failed','quarantined','uninstalling','uninstalled')),
          CHECK (approved_by IS NULL OR approved_by <> installed_by)
        );
        CREATE INDEX ix_skill_installations_status_environment ON skill_installations(status, environment);

        CREATE TABLE skill_install_plans (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          registered_skill_id UUID NOT NULL REFERENCES registered_skills(id),
          target_version_id UUID NOT NULL REFERENCES registered_skill_versions(id),
          environment VARCHAR(32) NOT NULL,
          plan JSONB NOT NULL,
          plan_checksum VARCHAR(128) NOT NULL,
          approval_required BOOLEAN NOT NULL,
          status VARCHAR(32) NOT NULL DEFAULT 'ready',
          created_by UUID NOT NULL REFERENCES users(id),
          expires_at TIMESTAMPTZ NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (status IN ('ready','approved','consumed','expired','rejected'))
        );

        CREATE TABLE skill_executions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          installation_id UUID NOT NULL REFERENCES skill_installations(id),
          skill_version_id UUID NOT NULL REFERENCES registered_skill_versions(id),
          actor_user_id UUID REFERENCES users(id),
          invocation_source VARCHAR(32) NOT NULL,
          invocation_reference_id UUID,
          status VARCHAR(32) NOT NULL DEFAULT 'created',
          input_encrypted JSONB NOT NULL,
          input_hash VARCHAR(128) NOT NULL,
          output_encrypted JSONB,
          output_hash VARCHAR(128),
          idempotency_key VARCHAR(128),
          permission_snapshot JSONB NOT NULL,
          configuration_version INTEGER NOT NULL,
          timeout_at TIMESTAMPTZ NOT NULL,
          started_at TIMESTAMPTZ,
          completed_at TIMESTAMPTZ,
          error_code VARCHAR(128),
          error_message_safe TEXT,
          trace_id VARCHAR(64),
          request_id UUID,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (invocation_source IN ('user_api','admin_api','agent','event','schedule','workflow','cli','ide','internal_service')),
          CHECK (status IN ('created','validating','authorizing','queued','running','waiting_for_confirmation','waiting_for_dependency','succeeded','partially_succeeded','failed','cancel_requested','cancelled','timed_out','compensating','compensated')),
          UNIQUE(installation_id, actor_user_id, idempotency_key)
        );
        CREATE INDEX ix_skill_executions_status_created ON skill_executions(status, created_at DESC);

        CREATE TABLE skill_signature_revocations (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          publisher_id UUID NOT NULL REFERENCES skill_publishers(id),
          key_id VARCHAR(255) NOT NULL,
          package_checksum VARCHAR(128),
          reason_code VARCHAR(128) NOT NULL,
          reason_encrypted TEXT,
          revoked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          revoked_by UUID NOT NULL REFERENCES users(id)
        );

        CREATE TABLE marketplace_listings (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          registered_skill_id UUID NOT NULL UNIQUE REFERENCES registered_skills(id),
          listing_status VARCHAR(32) NOT NULL DEFAULT 'draft',
          visibility VARCHAR(32) NOT NULL DEFAULT 'unlisted',
          category_codes JSONB NOT NULL,
          summary_localizations JSONB NOT NULL,
          documentation_reference TEXT,
          pricing_model VARCHAR(32) NOT NULL DEFAULT 'free',
          pricing_manifest JSONB,
          support_policy JSONB NOT NULL,
          privacy_disclosure JSONB NOT NULL,
          reviewed_version_id UUID REFERENCES registered_skill_versions(id),
          published_at TIMESTAMPTZ,
          suspended_at TIMESTAMPTZ,
          created_by UUID NOT NULL REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (listing_status IN ('draft','submitted','automated_review','human_review','changes_required','approved','published','suspended','removed','appeal_pending')),
          CHECK (visibility IN ('unlisted','private','public')),
          CHECK (pricing_model IN ('free','private_contract'))
        );

        CREATE TABLE marketplace_reviews (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          listing_id UUID NOT NULL REFERENCES marketplace_listings(id),
          skill_version_id UUID NOT NULL REFERENCES registered_skill_versions(id),
          review_type VARCHAR(32) NOT NULL,
          status VARCHAR(32) NOT NULL,
          report JSONB NOT NULL,
          package_checksum VARCHAR(128) NOT NULL,
          reviewer_id UUID REFERENCES users(id),
          completed_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (review_type IN ('automated','human','security')),
          CHECK (status IN ('pending','passed','failed','changes_required'))
        );

        CREATE TABLE marketplace_appeals (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          listing_id UUID NOT NULL REFERENCES marketplace_listings(id),
          publisher_id UUID NOT NULL REFERENCES skill_publishers(id),
          reason_code VARCHAR(128) NOT NULL,
          statement_encrypted TEXT NOT NULL,
          status VARCHAR(32) NOT NULL DEFAULT 'pending',
          decided_by UUID REFERENCES users(id),
          decision_reason_encrypted TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          decided_at TIMESTAMPTZ,
          CHECK (status IN ('pending','accepted','rejected'))
        );
        """
    )


def downgrade() -> None:
    _run(
        """
        DROP TABLE marketplace_appeals;
        DROP TABLE marketplace_reviews;
        DROP TABLE marketplace_listings;
        DROP TABLE skill_signature_revocations;
        DROP TABLE skill_executions;
        DROP TABLE skill_install_plans;
        DROP TABLE skill_installations;
        DROP TABLE skill_compatibility_records;
        DROP TABLE skill_dependencies;
        ALTER TABLE registered_skills DROP CONSTRAINT fk_registered_skills_latest_version;
        ALTER TABLE registered_skills DROP CONSTRAINT fk_registered_skills_stable_version;
        DROP TABLE registered_skill_versions;
        DROP TABLE registered_skills;
        DROP TABLE skill_publishers;
        """
    )
