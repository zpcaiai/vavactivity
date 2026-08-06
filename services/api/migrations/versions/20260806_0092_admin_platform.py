# ruff: noqa: E501

"""Create Batch 26 administration control plane.

Revision ID: 20260806_0092
Revises: 20260806_0091
"""

from alembic import op

revision = "20260806_0092"
down_revision = "20260806_0091"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(
        """
        CREATE TABLE admin_capability_definitions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), capability_code VARCHAR(255) NOT NULL,
          semantic_version VARCHAR(64) NOT NULL, display_name VARCHAR(300) NOT NULL,
          description TEXT NOT NULL, owning_module VARCHAR(64) NOT NULL,
          target_entity_type VARCHAR(128), capability_type VARCHAR(32) NOT NULL,
          risk_level VARCHAR(32) NOT NULL, required_permissions JSONB NOT NULL,
          required_purposes JSONB NOT NULL DEFAULT '[]'::jsonb,
          step_up_authentication_required BOOLEAN NOT NULL DEFAULT false,
          approval_policy_code VARCHAR(128), idempotency_required BOOLEAN NOT NULL,
          audit_level VARCHAR(32) NOT NULL, admin_route_code VARCHAR(128),
          api_operation_id VARCHAR(255), command_code VARCHAR(128),
          lifecycle_status VARCHAR(32) NOT NULL DEFAULT 'active', created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(capability_code,semantic_version),
          CHECK (capability_type IN ('view','search','create','update','review','approve','execute','retry','repair','export','configure','reveal_sensitive')),
          CHECK (risk_level IN ('low','moderate','high','critical')),
          CHECK (lifecycle_status IN ('draft','active','deprecated','retired')),
          CHECK (capability_type IN ('view','search') OR command_code IS NOT NULL),
          CHECK (risk_level NOT IN ('high','critical') OR audit_level='full_metadata')
        );
        CREATE TABLE admin_work_items (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), work_item_code VARCHAR(128) NOT NULL,
          work_item_type VARCHAR(64) NOT NULL, source_module VARCHAR(64) NOT NULL,
          source_entity_type VARCHAR(64), source_entity_id UUID, status VARCHAR(32) NOT NULL DEFAULT 'available',
          priority VARCHAR(32) NOT NULL, title_snapshot VARCHAR(500) NOT NULL, safe_summary TEXT,
          assigned_team VARCHAR(128), assigned_to UUID REFERENCES users(id), required_capability_code VARCHAR(255),
          action_route_code VARCHAR(128), action_route_params_encrypted JSONB,
          available_at TIMESTAMPTZ NOT NULL DEFAULT now(), due_at TIMESTAMPTZ, expires_at TIMESTAMPTZ,
          deduplication_key VARCHAR(255) NOT NULL UNIQUE, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), completed_at TIMESTAMPTZ,
          CHECK (status IN ('available','assigned','in_progress','waiting_for_information','waiting_for_approval','resolved','cancelled','expired','invalidated')),
          CHECK (priority IN ('low','normal','high','critical'))
        );
        CREATE TABLE admin_entity_view_definitions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), entity_view_code VARCHAR(255) NOT NULL,
          semantic_version VARCHAR(64) NOT NULL, entity_type VARCHAR(128) NOT NULL,
          section_manifest JSONB NOT NULL, relation_manifest JSONB NOT NULL,
          timeline_manifest JSONB NOT NULL, operation_manifest JSONB NOT NULL,
          default_masking_policy_code VARCHAR(128) NOT NULL, lifecycle_status VARCHAR(32) NOT NULL DEFAULT 'active',
          UNIQUE(entity_view_code,semantic_version)
        );
        CREATE TABLE admin_query_definitions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), query_code VARCHAR(255) NOT NULL,
          semantic_version VARCHAR(64) NOT NULL, owning_module VARCHAR(64) NOT NULL,
          target_entity_type VARCHAR(128) NOT NULL, filter_schema JSONB NOT NULL,
          sort_schema JSONB NOT NULL, column_schema JSONB NOT NULL, maximum_page_size INTEGER NOT NULL,
          export_policy JSONB NOT NULL, required_permissions JSONB NOT NULL,
          lifecycle_status VARCHAR(32) NOT NULL DEFAULT 'active', UNIQUE(query_code,semantic_version),
          CHECK (maximum_page_size BETWEEN 1 AND 500)
        );
        CREATE TABLE admin_saved_views (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), owner_user_id UUID NOT NULL REFERENCES users(id),
          query_code VARCHAR(255) NOT NULL, name VARCHAR(300) NOT NULL, description VARCHAR(1000),
          filter_definition JSONB NOT NULL, sort_definition JSONB NOT NULL, column_definition JSONB NOT NULL,
          visibility VARCHAR(32) NOT NULL, shared_team VARCHAR(128), is_default BOOLEAN NOT NULL DEFAULT false,
          version INTEGER NOT NULL DEFAULT 1, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (visibility IN ('private','team','organization_template')),
          CHECK (visibility<>'team' OR shared_team IS NOT NULL)
        );
        CREATE TABLE admin_bulk_operation_definitions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), operation_code VARCHAR(255) NOT NULL,
          semantic_version VARCHAR(64) NOT NULL, owning_module VARCHAR(64) NOT NULL,
          target_entity_type VARCHAR(128) NOT NULL, command_code VARCHAR(128) NOT NULL,
          eligibility_policy JSONB NOT NULL, maximum_batch_size INTEGER NOT NULL,
          risk_level VARCHAR(32) NOT NULL, dry_run_required BOOLEAN NOT NULL DEFAULT true,
          approval_policy_code VARCHAR(128), idempotency_policy JSONB NOT NULL, retry_policy JSONB NOT NULL,
          lifecycle_status VARCHAR(32) NOT NULL DEFAULT 'active', UNIQUE(operation_code,semantic_version),
          CHECK (maximum_batch_size BETWEEN 1 AND 10000),
          CHECK (command_code !~* '(direct_sql|set_state|mark_paid|fabricate)'),
          CHECK (risk_level NOT IN ('high','critical') OR approval_policy_code IS NOT NULL)
        );
        CREATE TABLE admin_bulk_jobs (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), operation_definition_id UUID NOT NULL REFERENCES admin_bulk_operation_definitions(id),
          requested_by UUID NOT NULL REFERENCES users(id), approved_by UUID REFERENCES users(id),
          selection_type VARCHAR(32) NOT NULL, selection_snapshot JSONB NOT NULL,
          input_parameters_encrypted JSONB NOT NULL, input_hash VARCHAR(128) NOT NULL,
          dry_run BOOLEAN NOT NULL, status VARCHAR(32) NOT NULL DEFAULT 'planned',
          total_count BIGINT NOT NULL DEFAULT 0, eligible_count BIGINT NOT NULL DEFAULT 0,
          succeeded_count BIGINT NOT NULL DEFAULT 0, skipped_count BIGINT NOT NULL DEFAULT 0, failed_count BIGINT NOT NULL DEFAULT 0,
          idempotency_key VARCHAR(128) NOT NULL UNIQUE, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), started_at TIMESTAMPTZ, completed_at TIMESTAMPTZ,
          CHECK (selection_type IN ('explicit_ids','saved_view_snapshot','query_snapshot')),
          CHECK (status IN ('planned','dry_run_completed','approval_required','approved','running','partially_failed','completed','failed','cancelled')),
          CHECK (approved_by IS NULL OR approved_by<>requested_by)
        );
        CREATE TABLE admin_bulk_job_items (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), bulk_job_id UUID NOT NULL REFERENCES admin_bulk_jobs(id) ON DELETE CASCADE,
          target_entity_id UUID NOT NULL, expected_entity_version INTEGER, status VARCHAR(32) NOT NULL DEFAULT 'eligible',
          eligibility_reason_code VARCHAR(128), command_execution_id UUID, error_code VARCHAR(128), processed_at TIMESTAMPTZ,
          UNIQUE(bulk_job_id,target_entity_id), CHECK (status IN ('eligible','ineligible','pending','succeeded','skipped','failed','retryable'))
        );
        CREATE TABLE admin_approval_policies (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), policy_code VARCHAR(128) NOT NULL,
          semantic_version VARCHAR(64) NOT NULL, applicable_capability_codes JSONB NOT NULL,
          approval_steps JSONB NOT NULL, separation_policy JSONB NOT NULL, validity_seconds BIGINT NOT NULL,
          step_up_authentication_required BOOLEAN NOT NULL, lifecycle_status VARCHAR(32) NOT NULL DEFAULT 'active',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(policy_code,semantic_version),
          CHECK (validity_seconds BETWEEN 60 AND 604800)
        );
        CREATE TABLE admin_approval_requests (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), approval_number VARCHAR(64) NOT NULL UNIQUE,
          policy_id UUID NOT NULL REFERENCES admin_approval_policies(id), requested_capability_code VARCHAR(255) NOT NULL,
          target_entity_type VARCHAR(128), target_entity_id UUID, requested_by UUID NOT NULL REFERENCES users(id),
          request_payload_encrypted JSONB NOT NULL, request_hash VARCHAR(128) NOT NULL, status VARCHAR(32) NOT NULL DEFAULT 'submitted',
          business_state_snapshot JSONB NOT NULL, expires_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          approved_at TIMESTAMPTZ, rejected_at TIMESTAMPTZ, executed_at TIMESTAMPTZ,
          CHECK (status IN ('draft','submitted','in_review','approved','rejected','withdrawn','expired','executing','executed','execution_failed','invalidated'))
        );
        CREATE TABLE admin_approval_decisions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), approval_request_id UUID NOT NULL REFERENCES admin_approval_requests(id) ON DELETE CASCADE,
          step_number INTEGER NOT NULL, reviewer_user_id UUID NOT NULL REFERENCES users(id), decision VARCHAR(32) NOT NULL,
          reason_code VARCHAR(128), rationale_encrypted TEXT, decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(approval_request_id,step_number,reviewer_user_id), CHECK (decision IN ('approved','rejected'))
        );
        CREATE TABLE admin_exception_items (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), exception_code VARCHAR(128) NOT NULL UNIQUE,
          exception_type VARCHAR(64) NOT NULL, source_module VARCHAR(64) NOT NULL,
          source_reference_type VARCHAR(64) NOT NULL, source_reference_id UUID NOT NULL,
          severity VARCHAR(32) NOT NULL, status VARCHAR(32) NOT NULL DEFAULT 'open', safe_summary TEXT NOT NULL,
          evidence_reference JSONB NOT NULL, allowed_diagnostic_codes JSONB NOT NULL, allowed_repair_codes JSONB NOT NULL,
          assigned_team VARCHAR(128), assigned_to UUID REFERENCES users(id), detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          due_at TIMESTAMPTZ, resolved_at TIMESTAMPTZ, resolution_reference_id UUID,
          CHECK (status IN ('open','diagnosing','repair_planned','repairing','verification_required','resolved','accepted_exception'))
        );
        CREATE TABLE admin_configuration_namespaces (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), namespace_code VARCHAR(255) NOT NULL UNIQUE,
          owning_module VARCHAR(64) NOT NULL, display_name VARCHAR(300) NOT NULL, description TEXT NOT NULL,
          schema_definition JSONB NOT NULL, environment_scope JSONB NOT NULL, approval_policy_code VARCHAR(128),
          secret_fields JSONB NOT NULL DEFAULT '[]'::jsonb, lifecycle_status VARCHAR(32) NOT NULL DEFAULT 'active', created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE admin_configuration_versions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), namespace_id UUID NOT NULL REFERENCES admin_configuration_namespaces(id),
          environment VARCHAR(32) NOT NULL, version_number INTEGER NOT NULL, semantic_version VARCHAR(64) NOT NULL,
          configuration_encrypted JSONB NOT NULL, non_secret_checksum VARCHAR(128) NOT NULL,
          status VARCHAR(32) NOT NULL DEFAULT 'draft', created_by UUID NOT NULL REFERENCES users(id), approved_by UUID REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(), approved_at TIMESTAMPTZ, activated_at TIMESTAMPTZ,
          UNIQUE(namespace_id,environment,version_number),
          CHECK (status IN ('draft','review_required','approved','scheduled','active','superseded','rolled_back','rejected')),
          CHECK (approved_by IS NULL OR approved_by<>created_by)
        );
        CREATE TABLE admin_field_access_policies (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), policy_code VARCHAR(255) NOT NULL,
          semantic_version VARCHAR(64) NOT NULL, asset_code VARCHAR(255) NOT NULL, field_path VARCHAR(500) NOT NULL,
          classification VARCHAR(32) NOT NULL, allowed_permissions JSONB NOT NULL, allowed_purposes JSONB NOT NULL,
          default_masking_rule VARCHAR(64) NOT NULL, reveal_allowed BOOLEAN NOT NULL, step_up_required BOOLEAN NOT NULL,
          reveal_duration_seconds INTEGER, export_allowed BOOLEAN NOT NULL, lifecycle_status VARCHAR(32) NOT NULL DEFAULT 'active',
          UNIQUE(policy_code,semantic_version), CHECK (classification IN ('public','internal','restricted','highly_restricted')),
          CHECK (default_masking_rule IN ('full','last_four','partial_email','partial_phone','hashed_reference','redacted_text','date_year_only','range_only','none'))
        );
        CREATE TABLE admin_sensitive_reveal_grants (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), admin_user_id UUID NOT NULL REFERENCES users(id),
          policy_id UUID NOT NULL REFERENCES admin_field_access_policies(id), entity_type VARCHAR(128) NOT NULL, entity_id UUID NOT NULL,
          purpose_code VARCHAR(128) NOT NULL, reason_encrypted TEXT NOT NULL, status VARCHAR(32) NOT NULL DEFAULT 'active',
          issued_at TIMESTAMPTZ NOT NULL DEFAULT now(), expires_at TIMESTAMPTZ NOT NULL, revoked_at TIMESTAMPTZ,
          CHECK (status IN ('active','expired','revoked'))
        );
        CREATE TABLE admin_operation_receipts (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), capability_code VARCHAR(255) NOT NULL,
          admin_user_id UUID NOT NULL REFERENCES users(id), target_entity_type VARCHAR(128), target_entity_id UUID,
          status VARCHAR(32) NOT NULL, command_execution_id UUID, approval_request_id UUID,
          before_version INTEGER, after_version INTEGER, emitted_event_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
          safe_result_summary TEXT, error_code VARCHAR(128), request_id UUID NOT NULL, trace_id VARCHAR(64),
          executed_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE admin_domain_certifications (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(), business_domain VARCHAR(64) NOT NULL,
          release_version VARCHAR(64) NOT NULL, environment VARCHAR(32) NOT NULL,
          required_capability_count INTEGER NOT NULL, implemented_capability_count INTEGER NOT NULL,
          verified_capability_count INTEGER NOT NULL, observable_coverage_ratio NUMERIC(6,5) NOT NULL,
          operable_coverage_ratio NUMERIC(6,5) NOT NULL, approval_coverage_ratio NUMERIC(6,5) NOT NULL,
          recovery_coverage_ratio NUMERIC(6,5) NOT NULL, masking_coverage_ratio NUMERIC(6,5) NOT NULL,
          audit_coverage_ratio NUMERIC(6,5) NOT NULL, unresolved_critical_gaps INTEGER NOT NULL,
          status VARCHAR(32) NOT NULL DEFAULT 'not_certified', evidence_ids JSONB NOT NULL,
          evaluated_by UUID REFERENCES users(id), certified_by UUID REFERENCES users(id), evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now(), certified_at TIMESTAMPTZ,
          UNIQUE(business_domain,release_version,environment),
          CHECK (status IN ('not_certified','eligible','certified','rejected')),
          CHECK (certified_by IS NULL OR certified_by<>evaluated_by)
        );
        """
    )


def downgrade() -> None:
    _run(
        """
        DROP TABLE IF EXISTS admin_domain_certifications;
        DROP TABLE IF EXISTS admin_operation_receipts;
        DROP TABLE IF EXISTS admin_sensitive_reveal_grants;
        DROP TABLE IF EXISTS admin_field_access_policies;
        DROP TABLE IF EXISTS admin_configuration_versions;
        DROP TABLE IF EXISTS admin_configuration_namespaces;
        DROP TABLE IF EXISTS admin_exception_items;
        DROP TABLE IF EXISTS admin_approval_decisions;
        DROP TABLE IF EXISTS admin_approval_requests;
        DROP TABLE IF EXISTS admin_approval_policies;
        DROP TABLE IF EXISTS admin_bulk_job_items;
        DROP TABLE IF EXISTS admin_bulk_jobs;
        DROP TABLE IF EXISTS admin_bulk_operation_definitions;
        DROP TABLE IF EXISTS admin_saved_views;
        DROP TABLE IF EXISTS admin_query_definitions;
        DROP TABLE IF EXISTS admin_entity_view_definitions;
        DROP TABLE IF EXISTS admin_work_items;
        DROP TABLE IF EXISTS admin_capability_definitions;
        """
    )
