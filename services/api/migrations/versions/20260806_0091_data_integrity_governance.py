"""Create Batch 25 data-integrity governance.

Revision ID: 20260806_0091
Revises: 20260806_0090
"""

# ruff: noqa: E501

from alembic import op

revision = "20260806_0091"
down_revision = "20260806_0090"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(
        """
        CREATE TABLE data_assets (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          asset_code VARCHAR(255) NOT NULL UNIQUE,
          display_name VARCHAR(300) NOT NULL,
          asset_type VARCHAR(64) NOT NULL,
          owning_module VARCHAR(64) NOT NULL,
          owning_service VARCHAR(128) NOT NULL,
          source_of_truth BOOLEAN NOT NULL,
          projection BOOLEAN NOT NULL,
          rebuildable BOOLEAN NOT NULL,
          data_steward_team VARCHAR(128) NOT NULL,
          classification VARCHAR(32) NOT NULL,
          retention_policy_code VARCHAR(128) NOT NULL,
          erasure_policy_code VARCHAR(128) NOT NULL,
          canonical_identifier_policy JSONB NOT NULL,
          version_policy JSONB NOT NULL,
          mutation_policy JSONB NOT NULL,
          storage_location_type VARCHAR(64) NOT NULL,
          storage_reference VARCHAR(1000),
          lifecycle_status VARCHAR(32) NOT NULL DEFAULT 'active',
          manifest_checksum_sha256 VARCHAR(64) NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (asset_type IN ('database_table','database_view','api_projection','event_stream','cache','search_index','vector_index','object_collection','file_export','analytics_dataset')),
          CHECK (classification IN ('public','internal','restricted','highly_restricted')),
          CHECK (lifecycle_status IN ('draft','active','deprecated','retired','quarantined')),
          CHECK (source_of_truth<>projection),
          CHECK (NOT projection OR rebuildable),
          CHECK (manifest_checksum_sha256 ~ '^[0-9a-f]{64}$')
        );

        CREATE TABLE canonical_external_identifiers (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entity_type VARCHAR(128) NOT NULL,
          canonical_entity_id UUID NOT NULL,
          provider_code VARCHAR(128) NOT NULL,
          external_identifier_hash VARCHAR(255) NOT NULL,
          external_identifier_encrypted TEXT,
          status VARCHAR(32) NOT NULL DEFAULT 'active',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          revoked_at TIMESTAMPTZ,
          UNIQUE(entity_type,provider_code,external_identifier_hash),
          CHECK (status IN ('active','revoked')),
          CHECK (external_identifier_hash !~* '@|\\+?[0-9]{7,}')
        );

        CREATE TABLE data_contracts (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          contract_code VARCHAR(255) NOT NULL,
          semantic_version VARCHAR(32) NOT NULL,
          contract_type VARCHAR(32) NOT NULL,
          asset_id UUID NOT NULL REFERENCES data_assets(id),
          producer_module VARCHAR(64) NOT NULL,
          consumer_modules JSONB NOT NULL,
          schema_definition JSONB NOT NULL,
          field_policies JSONB NOT NULL,
          compatibility_policy VARCHAR(32) NOT NULL,
          quality_expectations JSONB NOT NULL,
          migration_plan JSONB NOT NULL DEFAULT '{}'::jsonb,
          status VARCHAR(24) NOT NULL DEFAULT 'draft',
          schema_checksum_sha256 VARCHAR(64) NOT NULL,
          activated_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(contract_code,semantic_version),
          CHECK (contract_type IN ('table','api_request','api_response','event','file','search','vector','analytics','projection')),
          CHECK (compatibility_policy IN ('backward','forward','full','none')),
          CHECK (status IN ('draft','active','rejected','retired')),
          CHECK (schema_checksum_sha256 ~ '^[0-9a-f]{64}$')
        );

        CREATE UNIQUE INDEX uq_data_contract_active ON data_contracts(contract_code) WHERE status='active';

        CREATE TABLE data_contract_diffs (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          contract_code VARCHAR(255) NOT NULL,
          from_version VARCHAR(32) NOT NULL,
          to_version VARCHAR(32) NOT NULL,
          changes JSONB NOT NULL,
          compatibility_status VARCHAR(32) NOT NULL,
          breaking_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
          evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (compatibility_status IN ('compatible','breaking','not_evaluated'))
        );

        CREATE TABLE data_lineage_edges (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          source_asset_id UUID NOT NULL REFERENCES data_assets(id),
          target_asset_id UUID NOT NULL REFERENCES data_assets(id),
          transformation_type VARCHAR(32) NOT NULL,
          field_mapping JSONB NOT NULL DEFAULT '{}'::jsonb,
          propagation_mode VARCHAR(32) NOT NULL,
          expected_lag_seconds INTEGER NOT NULL DEFAULT 0,
          erasure_propagation BOOLEAN NOT NULL,
          retention_inheritance BOOLEAN NOT NULL,
          release_version VARCHAR(64) NOT NULL,
          active BOOLEAN NOT NULL DEFAULT true,
          UNIQUE(source_asset_id,target_asset_id,transformation_type),
          CHECK (source_asset_id<>target_asset_id),
          CHECK (transformation_type IN ('copy','filter','aggregate','mask','anonymize','embed','index','cache','export','event_projection','derive')),
          CHECK (propagation_mode IN ('synchronous','outbox_event','scheduled','on_demand')),
          CHECK (expected_lag_seconds>=0)
        );

        CREATE TABLE data_event_outbox (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          event_id UUID NOT NULL UNIQUE,
          event_type VARCHAR(255) NOT NULL,
          event_version INTEGER NOT NULL,
          aggregate_type VARCHAR(128) NOT NULL,
          aggregate_id UUID NOT NULL,
          aggregate_version BIGINT NOT NULL,
          sequence_number BIGINT NOT NULL,
          occurred_at TIMESTAMPTZ NOT NULL,
          producer_module VARCHAR(64) NOT NULL,
          correlation_id UUID,
          causation_id UUID,
          subject_user_id UUID,
          payload JSONB NOT NULL,
          metadata JSONB NOT NULL,
          payload_checksum_sha256 VARCHAR(64) NOT NULL,
          status VARCHAR(24) NOT NULL DEFAULT 'pending',
          attempt_count INTEGER NOT NULL DEFAULT 0,
          next_attempt_at TIMESTAMPTZ,
          published_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(producer_module,aggregate_type,aggregate_id,aggregate_version),
          CHECK (event_version>0 AND aggregate_version>0 AND sequence_number>0),
          CHECK (status IN ('pending','publishing','published','failed','dead_letter')),
          CHECK (payload_checksum_sha256 ~ '^[0-9a-f]{64}$')
        );

        CREATE INDEX ix_data_outbox_dispatch ON data_event_outbox(status,next_attempt_at,created_at);

        CREATE TABLE data_event_inbox (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          consumer_code VARCHAR(128) NOT NULL,
          event_id UUID NOT NULL,
          event_type VARCHAR(255) NOT NULL,
          aggregate_type VARCHAR(128) NOT NULL,
          aggregate_id UUID NOT NULL,
          aggregate_version BIGINT NOT NULL,
          payload_checksum_sha256 VARCHAR(64) NOT NULL,
          disposition VARCHAR(32) NOT NULL,
          effect_receipt JSONB NOT NULL DEFAULT '{}'::jsonb,
          received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          applied_at TIMESTAMPTZ,
          UNIQUE(consumer_code,event_id),
          CHECK (disposition IN ('accepted','duplicate','buffered_future','rejected_old','incompatible','failed')),
          CHECK (payload_checksum_sha256 ~ '^[0-9a-f]{64}$')
        );

        CREATE TABLE data_event_gaps (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          gap_code VARCHAR(255) NOT NULL UNIQUE,
          consumer_code VARCHAR(128) NOT NULL,
          aggregate_type VARCHAR(128) NOT NULL,
          aggregate_id UUID NOT NULL,
          expected_version BIGINT NOT NULL,
          received_version BIGINT NOT NULL,
          severity VARCHAR(16) NOT NULL,
          status VARCHAR(24) NOT NULL DEFAULT 'open',
          detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          resolved_at TIMESTAMPTZ,
          CHECK (received_version>expected_version),
          CHECK (severity IN ('low','medium','high','critical')),
          CHECK (status IN ('open','recovering','resolved','false_positive'))
        );

        CREATE TABLE data_dead_letters (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          event_id UUID NOT NULL,
          consumer_code VARCHAR(128) NOT NULL,
          event_type VARCHAR(255) NOT NULL,
          affected_entity_type VARCHAR(128) NOT NULL,
          affected_entity_id UUID NOT NULL,
          failure_code VARCHAR(128) NOT NULL,
          failure_detail JSONB NOT NULL,
          payload_reference VARCHAR(500) NOT NULL,
          status VARCHAR(24) NOT NULL DEFAULT 'open',
          replay_count INTEGER NOT NULL DEFAULT 0,
          replay_policy JSONB NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          resolved_at TIMESTAMPTZ,
          UNIQUE(event_id,consumer_code),
          CHECK (status IN ('open','quarantined','replaying','resolved','discarded_with_approval'))
        );

        CREATE TABLE data_quality_rules (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          rule_code VARCHAR(255) NOT NULL,
          version INTEGER NOT NULL,
          asset_id UUID NOT NULL REFERENCES data_assets(id),
          dimension VARCHAR(32) NOT NULL,
          severity VARCHAR(16) NOT NULL,
          declarative_rule JSONB NOT NULL,
          sample_policy JSONB NOT NULL,
          schedule_policy JSONB NOT NULL,
          status VARCHAR(24) NOT NULL DEFAULT 'active',
          UNIQUE(rule_code,version),
          CHECK (dimension IN ('completeness','validity','uniqueness','consistency','referential_integrity','timeliness','freshness','conformance','drift','nullability')),
          CHECK (severity IN ('low','medium','high','critical')),
          CHECK (status IN ('draft','active','disabled','retired'))
        );

        CREATE TABLE data_quality_evaluations (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          rule_id UUID NOT NULL REFERENCES data_quality_rules(id),
          evaluated_records BIGINT NOT NULL,
          failed_records BIGINT NOT NULL,
          failure_rate NUMERIC(12,8) NOT NULL,
          minimized_sample JSONB NOT NULL,
          status VARCHAR(24) NOT NULL,
          evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (evaluated_records>=0 AND failed_records>=0 AND failed_records<=evaluated_records),
          CHECK (failure_rate BETWEEN 0 AND 1),
          CHECK (status IN ('pass','fail','not_run'))
        );

        CREATE TABLE data_reconciliation_definitions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          reconciliation_code VARCHAR(255) NOT NULL UNIQUE,
          source_asset_id UUID NOT NULL REFERENCES data_assets(id),
          target_asset_id UUID NOT NULL REFERENCES data_assets(id),
          authoritative_side VARCHAR(16) NOT NULL,
          comparison_keys JSONB NOT NULL,
          comparison_fields JSONB NOT NULL,
          severity VARCHAR(16) NOT NULL,
          repair_command_code VARCHAR(160),
          active BOOLEAN NOT NULL DEFAULT true,
          CHECK (authoritative_side IN ('source','target')),
          CHECK (severity IN ('low','medium','high','critical')),
          CHECK (repair_command_code IS NULL OR repair_command_code !~* '(direct_sql|set_state|mark_paid|fabricate)')
        );

        CREATE TABLE data_reconciliation_runs (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          definition_id UUID NOT NULL REFERENCES data_reconciliation_definitions(id),
          cursor_value VARCHAR(500),
          compared_count BIGINT NOT NULL DEFAULT 0,
          difference_count BIGINT NOT NULL DEFAULT 0,
          status VARCHAR(24) NOT NULL DEFAULT 'running',
          started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          completed_at TIMESTAMPTZ,
          CHECK (status IN ('running','completed','failed','cancelled'))
        );

        CREATE TABLE data_reconciliation_differences (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          run_id UUID NOT NULL REFERENCES data_reconciliation_runs(id) ON DELETE CASCADE,
          difference_key VARCHAR(255) NOT NULL,
          category VARCHAR(64) NOT NULL,
          severity VARCHAR(16) NOT NULL,
          source_fingerprint VARCHAR(64),
          target_fingerprint VARCHAR(64),
          minimized_evidence JSONB NOT NULL,
          status VARCHAR(24) NOT NULL DEFAULT 'open',
          assigned_to UUID REFERENCES users(id),
          resolved_at TIMESTAMPTZ,
          UNIQUE(run_id,difference_key),
          CHECK (severity IN ('low','medium','high','critical')),
          CHECK (status IN ('open','quarantined','repair_planned','resolved','accepted_exception'))
        );

        CREATE TABLE data_backfill_definitions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          backfill_code VARCHAR(255) NOT NULL UNIQUE,
          target_asset_id UUID NOT NULL REFERENCES data_assets(id),
          candidate_query_code VARCHAR(160) NOT NULL,
          transformation_code VARCHAR(160) NOT NULL,
          validation_code VARCHAR(160) NOT NULL,
          chunk_size INTEGER NOT NULL,
          rate_limit_per_minute INTEGER NOT NULL,
          approval_required BOOLEAN NOT NULL DEFAULT true,
          rollback_boundary JSONB NOT NULL,
          active BOOLEAN NOT NULL DEFAULT true,
          CHECK (chunk_size BETWEEN 1 AND 10000),
          CHECK (rate_limit_per_minute BETWEEN 1 AND 100000),
          CHECK (candidate_query_code !~* '(--|update |delete |insert )')
        );

        CREATE TABLE data_backfill_runs (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          definition_id UUID NOT NULL REFERENCES data_backfill_definitions(id),
          environment VARCHAR(32) NOT NULL,
          dry_run BOOLEAN NOT NULL,
          idempotency_key VARCHAR(255) NOT NULL UNIQUE,
          stable_candidate_hash VARCHAR(64) NOT NULL,
          cursor_value VARCHAR(500),
          processed_count BIGINT NOT NULL DEFAULT 0,
          success_count BIGINT NOT NULL DEFAULT 0,
          failure_count BIGINT NOT NULL DEFAULT 0,
          status VARCHAR(24) NOT NULL DEFAULT 'created',
          requested_by UUID REFERENCES users(id),
          approved_by UUID REFERENCES users(id),
          started_at TIMESTAMPTZ,
          completed_at TIMESTAMPTZ,
          CHECK (environment IN ('local','ci','staging','production')),
          CHECK (status IN ('created','approved','running','paused','completed','failed','cancelled')),
          CHECK (stable_candidate_hash ~ '^[0-9a-f]{64}$'),
          CHECK (approved_by IS NULL OR approved_by<>requested_by)
        );

        CREATE TABLE data_backfill_items (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          run_id UUID NOT NULL REFERENCES data_backfill_runs(id) ON DELETE CASCADE,
          item_key_hash VARCHAR(64) NOT NULL,
          input_version VARCHAR(128) NOT NULL,
          status VARCHAR(24) NOT NULL DEFAULT 'pending',
          attempt_count INTEGER NOT NULL DEFAULT 0,
          output_checksum_sha256 VARCHAR(64),
          minimized_error JSONB NOT NULL DEFAULT '{}'::jsonb,
          processed_at TIMESTAMPTZ,
          UNIQUE(run_id,item_key_hash),
          CHECK (item_key_hash ~ '^[0-9a-f]{64}$'),
          CHECK (status IN ('pending','running','succeeded','failed','skipped')),
          CHECK (output_checksum_sha256 IS NULL OR output_checksum_sha256 ~ '^[0-9a-f]{64}$')
        );

        CREATE TABLE data_repair_definitions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          repair_code VARCHAR(255) NOT NULL UNIQUE,
          owning_module VARCHAR(64) NOT NULL,
          repair_type VARCHAR(32) NOT NULL,
          command_code VARCHAR(160) NOT NULL,
          approval_required BOOLEAN NOT NULL,
          postconditions JSONB NOT NULL,
          active BOOLEAN NOT NULL DEFAULT true,
          CHECK (repair_type IN ('domain_command','projection_rebuild','event_replay','cache_invalidation','search_reindex','vector_reindex','object_cleanup')),
          CHECK (command_code !~* '(direct_sql|set_state|mark_paid|fabricate)')
        );

        CREATE TABLE data_repair_executions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          repair_definition_id UUID NOT NULL REFERENCES data_repair_definitions(id),
          reconciliation_difference_id UUID REFERENCES data_reconciliation_differences(id),
          idempotency_key VARCHAR(255) NOT NULL UNIQUE,
          input_mapping JSONB NOT NULL,
          status VARCHAR(24) NOT NULL DEFAULT 'requested',
          requested_by UUID REFERENCES users(id),
          approved_by UUID REFERENCES users(id),
          execution_receipt JSONB NOT NULL DEFAULT '{}'::jsonb,
          postcondition_results JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          completed_at TIMESTAMPTZ,
          CHECK (status IN ('requested','approved','running','succeeded','failed','rejected')),
          CHECK (approved_by IS NULL OR approved_by<>requested_by)
        );

        CREATE TABLE data_projection_rebuilds (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          asset_id UUID NOT NULL REFERENCES data_assets(id),
          scope VARCHAR(32) NOT NULL,
          scope_key VARCHAR(255),
          source_checkpoint JSONB NOT NULL,
          target_checkpoint JSONB NOT NULL DEFAULT '{}'::jsonb,
          shadow_build BOOLEAN NOT NULL DEFAULT false,
          validation_results JSONB NOT NULL DEFAULT '{}'::jsonb,
          status VARCHAR(24) NOT NULL DEFAULT 'created',
          requested_by UUID REFERENCES users(id),
          approved_by UUID REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          completed_at TIMESTAMPTZ,
          CHECK (scope IN ('entity','partition','full')),
          CHECK (status IN ('created','running','validating','switched','completed','failed','cancelled'))
        );

        CREATE TABLE data_erasure_plans (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          privacy_request_id UUID NOT NULL,
          subject_user_id UUID NOT NULL REFERENCES users(id),
          lineage_release_version VARCHAR(64) NOT NULL,
          status VARCHAR(32) NOT NULL DEFAULT 'planned',
          task_count INTEGER NOT NULL,
          completed_count INTEGER NOT NULL DEFAULT 0,
          failed_count INTEGER NOT NULL DEFAULT 0,
          legal_hold_count INTEGER NOT NULL DEFAULT 0,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          completed_at TIMESTAMPTZ,
          UNIQUE(privacy_request_id,lineage_release_version),
          CHECK (status IN ('planned','running','verification_failed','completed','blocked_legal_hold'))
        );

        CREATE TABLE data_erasure_tasks (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          plan_id UUID NOT NULL REFERENCES data_erasure_plans(id) ON DELETE CASCADE,
          asset_id UUID NOT NULL REFERENCES data_assets(id),
          action VARCHAR(32) NOT NULL,
          idempotency_key VARCHAR(255) NOT NULL UNIQUE,
          status VARCHAR(24) NOT NULL DEFAULT 'pending',
          legal_hold_reference VARCHAR(255),
          execution_receipt JSONB NOT NULL DEFAULT '{}'::jsonb,
          residual_count BIGINT,
          completed_at TIMESTAMPTZ,
          UNIQUE(plan_id,asset_id),
          CHECK (action IN ('delete','anonymize','remove_projection','invalidate_cache','remove_search','remove_vector','remove_object','remove_export','retain_legal_hold')),
          CHECK (status IN ('pending','running','completed','failed','retained_legal_hold')),
          CHECK (status<>'retained_legal_hold' OR legal_hold_reference IS NOT NULL)
        );

        CREATE TABLE data_erasure_certificates (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          plan_id UUID NOT NULL UNIQUE REFERENCES data_erasure_plans(id),
          subject_pseudonym VARCHAR(64) NOT NULL,
          result_summary JSONB NOT NULL,
          evidence_checksum_sha256 VARCHAR(64) NOT NULL,
          issued_by UUID REFERENCES users(id),
          issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (evidence_checksum_sha256 ~ '^[0-9a-f]{64}$')
        );

        CREATE TABLE data_integrity_certifications (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          business_domain VARCHAR(64) NOT NULL,
          git_commit VARCHAR(64) NOT NULL,
          environment VARCHAR(32) NOT NULL,
          evidence_results JSONB NOT NULL,
          open_critical_event_gaps INTEGER NOT NULL,
          open_critical_dead_letters INTEGER NOT NULL,
          open_critical_differences INTEGER NOT NULL,
          erasure_failures INTEGER NOT NULL,
          technical_status VARCHAR(24) NOT NULL,
          production_status VARCHAR(24) NOT NULL DEFAULT 'not_certified',
          evidence_checksum_sha256 VARCHAR(64) NOT NULL,
          evaluated_by UUID REFERENCES users(id),
          certified_by UUID REFERENCES users(id),
          evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          certified_at TIMESTAMPTZ,
          UNIQUE(business_domain,git_commit,environment),
          CHECK (environment IN ('local','ci','staging','production')),
          CHECK (technical_status IN ('pass','fail','not_run')),
          CHECK (production_status IN ('not_certified','certified','rejected')),
          CHECK (open_critical_event_gaps>=0 AND open_critical_dead_letters>=0 AND open_critical_differences>=0 AND erasure_failures>=0),
          CHECK (evidence_checksum_sha256 ~ '^[0-9a-f]{64}$'),
          CHECK (certified_by IS NULL OR certified_by<>evaluated_by)
        );
        """
    )


def downgrade() -> None:
    _run(
        """
        DROP TABLE IF EXISTS data_integrity_certifications;
        DROP TABLE IF EXISTS data_erasure_certificates;
        DROP TABLE IF EXISTS data_erasure_tasks;
        DROP TABLE IF EXISTS data_erasure_plans;
        DROP TABLE IF EXISTS data_projection_rebuilds;
        DROP TABLE IF EXISTS data_repair_executions;
        DROP TABLE IF EXISTS data_repair_definitions;
        DROP TABLE IF EXISTS data_backfill_items;
        DROP TABLE IF EXISTS data_backfill_runs;
        DROP TABLE IF EXISTS data_backfill_definitions;
        DROP TABLE IF EXISTS data_reconciliation_differences;
        DROP TABLE IF EXISTS data_reconciliation_runs;
        DROP TABLE IF EXISTS data_reconciliation_definitions;
        DROP TABLE IF EXISTS data_quality_evaluations;
        DROP TABLE IF EXISTS data_quality_rules;
        DROP TABLE IF EXISTS data_dead_letters;
        DROP TABLE IF EXISTS data_event_gaps;
        DROP TABLE IF EXISTS data_event_inbox;
        DROP TABLE IF EXISTS data_event_outbox;
        DROP TABLE IF EXISTS data_lineage_edges;
        DROP TABLE IF EXISTS data_contract_diffs;
        DROP TABLE IF EXISTS data_contracts;
        DROP TABLE IF EXISTS canonical_external_identifiers;
        DROP TABLE IF EXISTS data_assets;
        """
    )
