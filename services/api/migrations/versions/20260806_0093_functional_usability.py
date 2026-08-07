# ruff: noqa: E501

"""Create Batch 27 functional usability control plane.

Revision ID: 20260806_0093
Revises: 20260806_0092
"""

from alembic import op

revision = "20260806_0093"
down_revision = "20260806_0092"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(
        """
        CREATE TABLE usability_uat_scenarios (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), scenario_code VARCHAR(255) NOT NULL,
          semantic_version VARCHAR(64) NOT NULL, title VARCHAR(500) NOT NULL, persona_code VARCHAR(128) NOT NULL,
          business_domain VARCHAR(64) NOT NULL, criticality VARCHAR(16) NOT NULL,
          preconditions JSONB NOT NULL, steps JSONB NOT NULL, expected_outcomes JSONB NOT NULL,
          automation_level VARCHAR(32) NOT NULL, required_locales JSONB NOT NULL,
          required_device_profiles JSONB NOT NULL, lifecycle_status VARCHAR(24) NOT NULL DEFAULT 'active',
          UNIQUE(scenario_code,semantic_version), CHECK (criticality IN ('low','medium','high','critical')),
          CHECK (automation_level IN ('manual','assisted','automated','hybrid'))
        );
        CREATE TABLE usability_uat_runs (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), scenario_id UUID NOT NULL REFERENCES usability_uat_scenarios(id),
          environment VARCHAR(32) NOT NULL, release_version VARCHAR(64) NOT NULL, locale VARCHAR(32) NOT NULL,
          device_profile VARCHAR(128) NOT NULL, status VARCHAR(24) NOT NULL DEFAULT 'not_run',
          executed_by UUID REFERENCES users(id), evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
          started_at TIMESTAMPTZ, completed_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (status IN ('not_run','running','passed','failed','blocked','not_evaluated'))
        );
        CREATE TABLE usability_uat_step_results (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), run_id UUID NOT NULL REFERENCES usability_uat_runs(id) ON DELETE CASCADE,
          step_number INTEGER NOT NULL, status VARCHAR(24) NOT NULL, safe_observation TEXT,
          screenshot_ref VARCHAR(1000), error_code VARCHAR(128), duration_ms BIGINT,
          UNIQUE(run_id,step_number), CHECK (status IN ('not_run','passed','failed','blocked','skipped'))
        );
        CREATE TABLE usability_synthetic_blueprints (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), blueprint_code VARCHAR(255) NOT NULL,
          semantic_version VARCHAR(64) NOT NULL, persona_manifest JSONB NOT NULL, scenario_manifest JSONB NOT NULL,
          scale_profile VARCHAR(32) NOT NULL, deterministic_seed BIGINT NOT NULL,
          external_side_effects_allowed BOOLEAN NOT NULL DEFAULT false, lifecycle_status VARCHAR(24) NOT NULL DEFAULT 'active',
          UNIQUE(blueprint_code,semantic_version), CHECK (scale_profile IN ('minimal','standard','large','stress')),
          CHECK (external_side_effects_allowed=false)
        );
        CREATE TABLE usability_synthetic_runs (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), blueprint_id UUID NOT NULL REFERENCES usability_synthetic_blueprints(id),
          environment VARCHAR(32) NOT NULL, status VARCHAR(24) NOT NULL DEFAULT 'created',
          generated_counts JSONB NOT NULL DEFAULT '{}'::jsonb, cleanup_receipt JSONB NOT NULL DEFAULT '{}'::jsonb,
          requested_by UUID REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL DEFAULT now(), completed_at TIMESTAMPTZ,
          CHECK (status IN ('created','generating','ready','failed','cleaning','cleaned'))
        );
        CREATE TABLE usability_demo_environments (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), environment_code VARCHAR(128) NOT NULL UNIQUE,
          base_url VARCHAR(1000) NOT NULL, provider_profile VARCHAR(64) NOT NULL,
          synthetic_only BOOLEAN NOT NULL DEFAULT true, external_side_effects_disabled BOOLEAN NOT NULL DEFAULT true,
          status VARCHAR(24) NOT NULL DEFAULT 'disabled', reset_generation INTEGER NOT NULL DEFAULT 0,
          last_reset_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (provider_profile IN ('fake','sandbox','recorded')), CHECK (synthetic_only AND external_side_effects_disabled),
          CHECK (status IN ('disabled','provisioning','ready','resetting','failed'))
        );
        CREATE TABLE usability_compatibility_policies (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), policy_code VARCHAR(128) NOT NULL,
          semantic_version VARCHAR(64) NOT NULL, browser_matrix JSONB NOT NULL, device_matrix JSONB NOT NULL,
          input_matrix JSONB NOT NULL, network_matrix JSONB NOT NULL, critical_journeys JSONB NOT NULL,
          lifecycle_status VARCHAR(24) NOT NULL DEFAULT 'active', UNIQUE(policy_code,semantic_version)
        );
        CREATE TABLE usability_compatibility_runs (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), policy_id UUID NOT NULL REFERENCES usability_compatibility_policies(id),
          release_version VARCHAR(64) NOT NULL, environment VARCHAR(32) NOT NULL,
          browser VARCHAR(128) NOT NULL, device_profile VARCHAR(128) NOT NULL, network_profile VARCHAR(64) NOT NULL,
          status VARCHAR(24) NOT NULL DEFAULT 'not_run', evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
          executed_at TIMESTAMPTZ, CHECK (status IN ('not_run','passed','failed','blocked'))
        );
        CREATE TABLE usability_locale_registry (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), locale_code VARCHAR(32) NOT NULL UNIQUE,
          display_name VARCHAR(128) NOT NULL, direction VARCHAR(8) NOT NULL, fallback_locale VARCHAR(32),
          date_format VARCHAR(64) NOT NULL, time_format VARCHAR(64) NOT NULL, lifecycle_status VARCHAR(24) NOT NULL DEFAULT 'active',
          CHECK (direction IN ('ltr','rtl'))
        );
        CREATE TABLE usability_localization_runs (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), locale_code VARCHAR(32) NOT NULL,
          release_version VARCHAR(64) NOT NULL, environment VARCHAR(32) NOT NULL, pseudo_localization BOOLEAN NOT NULL,
          missing_keys INTEGER NOT NULL DEFAULT 0, overflow_findings INTEGER NOT NULL DEFAULT 0,
          unsafe_copy_findings INTEGER NOT NULL DEFAULT 0, status VARCHAR(24) NOT NULL DEFAULT 'not_run',
          evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb, executed_at TIMESTAMPTZ,
          CHECK (status IN ('not_run','passed','failed','blocked'))
        );
        CREATE TABLE usability_draft_definitions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), draft_code VARCHAR(255) NOT NULL,
          semantic_version VARCHAR(64) NOT NULL, owning_module VARCHAR(64) NOT NULL,
          schema_definition JSONB NOT NULL, sensitive_fields JSONB NOT NULL, ttl_seconds BIGINT NOT NULL,
          conflict_policy VARCHAR(32) NOT NULL, lifecycle_status VARCHAR(24) NOT NULL DEFAULT 'active',
          UNIQUE(draft_code,semantic_version), CHECK (ttl_seconds BETWEEN 60 AND 2592000),
          CHECK (conflict_policy IN ('latest_client','latest_server','manual_merge','reject_stale'))
        );
        CREATE TABLE usability_user_drafts (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), definition_id UUID NOT NULL REFERENCES usability_draft_definitions(id),
          user_id UUID NOT NULL REFERENCES users(id), entity_id UUID, schema_version VARCHAR(64) NOT NULL,
          encrypted_payload JSONB NOT NULL, payload_checksum VARCHAR(64) NOT NULL, client_version BIGINT NOT NULL,
          status VARCHAR(24) NOT NULL DEFAULT 'active', expires_at TIMESTAMPTZ NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(definition_id,user_id,entity_id), CHECK (status IN ('active','submitted','expired','discarded','migration_failed'))
        );
        CREATE TABLE usability_notification_qa_cases (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), case_code VARCHAR(255) NOT NULL,
          semantic_version VARCHAR(64) NOT NULL, event_type VARCHAR(255) NOT NULL, journey_state VARCHAR(128) NOT NULL,
          channels JSONB NOT NULL, expected_template_codes JSONB NOT NULL, forbidden_claims JSONB NOT NULL,
          expiry_policy JSONB NOT NULL, lifecycle_status VARCHAR(24) NOT NULL DEFAULT 'active', UNIQUE(case_code,semantic_version)
        );
        CREATE TABLE usability_import_definitions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), import_code VARCHAR(255) NOT NULL,
          semantic_version VARCHAR(64) NOT NULL, owning_module VARCHAR(64) NOT NULL, schema_definition JSONB NOT NULL,
          maximum_rows INTEGER NOT NULL, dry_run_required BOOLEAN NOT NULL DEFAULT true,
          command_code VARCHAR(128) NOT NULL, lifecycle_status VARCHAR(24) NOT NULL DEFAULT 'active',
          UNIQUE(import_code,semantic_version), CHECK (maximum_rows BETWEEN 1 AND 100000),
          CHECK (command_code !~* '(direct_sql|set_state|fabricate)')
        );
        CREATE TABLE usability_import_jobs (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), definition_id UUID NOT NULL REFERENCES usability_import_definitions(id),
          requested_by UUID NOT NULL REFERENCES users(id), source_file_ref VARCHAR(1000) NOT NULL,
          source_checksum VARCHAR(64) NOT NULL, dry_run BOOLEAN NOT NULL, idempotency_key VARCHAR(128) NOT NULL UNIQUE,
          status VARCHAR(24) NOT NULL DEFAULT 'created', total_rows BIGINT NOT NULL DEFAULT 0,
          valid_rows BIGINT NOT NULL DEFAULT 0, invalid_rows BIGINT NOT NULL DEFAULT 0,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(), completed_at TIMESTAMPTZ,
          CHECK (status IN ('created','validating','preview_ready','approval_required','importing','completed','partially_failed','failed','cancelled'))
        );
        CREATE TABLE usability_import_row_results (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), job_id UUID NOT NULL REFERENCES usability_import_jobs(id) ON DELETE CASCADE,
          row_number BIGINT NOT NULL, status VARCHAR(24) NOT NULL, safe_error_code VARCHAR(128), field_errors JSONB NOT NULL DEFAULT '{}'::jsonb,
          command_execution_id UUID, UNIQUE(job_id,row_number), CHECK (status IN ('valid','invalid','imported','failed','skipped'))
        );
        CREATE TABLE usability_support_playbooks (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), playbook_code VARCHAR(255) NOT NULL,
          semantic_version VARCHAR(64) NOT NULL, owning_module VARCHAR(64) NOT NULL, issue_type VARCHAR(128) NOT NULL,
          diagnostic_steps JSONB NOT NULL, allowed_resolution_codes JSONB NOT NULL, escalation_policy JSONB NOT NULL,
          safety_boundary JSONB NOT NULL, lifecycle_status VARCHAR(24) NOT NULL DEFAULT 'draft',
          UNIQUE(playbook_code,semantic_version)
        );
        CREATE TABLE usability_studies (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), study_code VARCHAR(255) NOT NULL UNIQUE,
          title VARCHAR(500) NOT NULL, target_personas JSONB NOT NULL, task_manifest JSONB NOT NULL,
          consent_template_code VARCHAR(128) NOT NULL, recording_policy JSONB NOT NULL,
          status VARCHAR(24) NOT NULL DEFAULT 'draft', created_by UUID REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (status IN ('draft','recruiting','running','analysis','completed','cancelled'))
        );
        CREATE TABLE usability_certifications (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), business_domain VARCHAR(64) NOT NULL,
          release_version VARCHAR(64) NOT NULL, environment VARCHAR(32) NOT NULL,
          uat_status VARCHAR(24) NOT NULL, compatibility_status VARCHAR(24) NOT NULL,
          localization_status VARCHAR(24) NOT NULL, draft_status VARCHAR(24) NOT NULL,
          notification_status VARCHAR(24) NOT NULL, import_export_status VARCHAR(24) NOT NULL,
          unresolved_critical_findings INTEGER NOT NULL, status VARCHAR(24) NOT NULL DEFAULT 'not_certified',
          evidence_refs JSONB NOT NULL, evaluated_by UUID REFERENCES users(id), certified_by UUID REFERENCES users(id),
          evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now(), certified_at TIMESTAMPTZ,
          UNIQUE(business_domain,release_version,environment),
          CHECK (status IN ('not_certified','eligible','certified','rejected')),
          CHECK (certified_by IS NULL OR certified_by<>evaluated_by)
        );
        """
    )


def downgrade() -> None:
    _run(
        """
        DROP TABLE IF EXISTS usability_certifications;
        DROP TABLE IF EXISTS usability_studies;
        DROP TABLE IF EXISTS usability_support_playbooks;
        DROP TABLE IF EXISTS usability_import_row_results;
        DROP TABLE IF EXISTS usability_import_jobs;
        DROP TABLE IF EXISTS usability_import_definitions;
        DROP TABLE IF EXISTS usability_notification_qa_cases;
        DROP TABLE IF EXISTS usability_user_drafts;
        DROP TABLE IF EXISTS usability_draft_definitions;
        DROP TABLE IF EXISTS usability_localization_runs;
        DROP TABLE IF EXISTS usability_locale_registry;
        DROP TABLE IF EXISTS usability_compatibility_runs;
        DROP TABLE IF EXISTS usability_compatibility_policies;
        DROP TABLE IF EXISTS usability_demo_environments;
        DROP TABLE IF EXISTS usability_synthetic_runs;
        DROP TABLE IF EXISTS usability_synthetic_blueprints;
        DROP TABLE IF EXISTS usability_uat_step_results;
        DROP TABLE IF EXISTS usability_uat_runs;
        DROP TABLE IF EXISTS usability_uat_scenarios;
        """
    )
