"""Create the Batch 24 process-governance control plane.

Revision ID: 20260806_0090
Revises: 20260806_0089
"""

# ruff: noqa: E501

from alembic import op

revision = "20260806_0090"
down_revision = "20260806_0089"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(
        """
        CREATE TABLE process_definitions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          process_code VARCHAR(128) NOT NULL,
          version INTEGER NOT NULL,
          process_type VARCHAR(32) NOT NULL,
          business_domain VARCHAR(64) NOT NULL,
          criticality VARCHAR(16) NOT NULL,
          owner_team VARCHAR(128) NOT NULL,
          participant_modules JSONB NOT NULL,
          actor_types JSONB NOT NULL,
          start_condition JSONB NOT NULL,
          terminal_states JSONB NOT NULL,
          sla_seconds INTEGER NOT NULL,
          cancellation_policy JSONB NOT NULL,
          compensation_policy JSONB NOT NULL,
          stuck_policy JSONB NOT NULL,
          status VARCHAR(24) NOT NULL DEFAULT 'draft',
          manifest_checksum_sha256 VARCHAR(64) NOT NULL,
          activated_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(process_code,version),
          CHECK (process_type IN ('local_transaction','orchestrated_saga','choreographed_process','human_workflow','scheduled_lifecycle','hybrid')),
          CHECK (criticality IN ('low','medium','high','critical')),
          CHECK (status IN ('draft','active','retired','invalid')),
          CHECK (sla_seconds BETWEEN 1 AND 31536000),
          CHECK (manifest_checksum_sha256 ~ '^[0-9a-f]{64}$')
        );

        CREATE UNIQUE INDEX uq_process_definition_active
          ON process_definitions(process_code) WHERE status='active';

        CREATE TABLE process_step_definitions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          process_definition_id UUID NOT NULL REFERENCES process_definitions(id) ON DELETE CASCADE,
          step_code VARCHAR(128) NOT NULL,
          sequence INTEGER NOT NULL,
          step_type VARCHAR(32) NOT NULL,
          owning_module VARCHAR(64) NOT NULL,
          command_code VARCHAR(160),
          expected_event_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
          preconditions JSONB NOT NULL DEFAULT '[]'::jsonb,
          postconditions JSONB NOT NULL DEFAULT '[]'::jsonb,
          timeout_seconds INTEGER,
          retry_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
          idempotency_scope VARCHAR(32),
          concurrency_mode VARCHAR(32),
          compensation_code VARCHAR(128),
          required BOOLEAN NOT NULL DEFAULT true,
          UNIQUE(process_definition_id,step_code),
          UNIQUE(process_definition_id,sequence),
          CHECK (step_type IN ('command','event_wait','human_task','provider_call','timer','condition','parallel','subprocess')),
          CHECK (idempotency_scope IS NULL OR idempotency_scope IN ('user_operation','business_entity','saga_step','event_consumer','provider_callback')),
          CHECK (concurrency_mode IS NULL OR concurrency_mode IN ('optimistic_lock','pessimistic_lock','unique_constraint','atomic_counter','advisory_lock','serialized_queue')),
          CHECK (timeout_seconds IS NULL OR timeout_seconds > 0),
          CHECK (command_code IS NULL OR command_code !~* '(direct_sql|set_state|fabricate)')
        );

        CREATE TABLE state_machine_definitions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          machine_code VARCHAR(128) NOT NULL,
          version INTEGER NOT NULL,
          owning_module VARCHAR(64) NOT NULL,
          aggregate_type VARCHAR(128) NOT NULL,
          initial_state VARCHAR(128) NOT NULL,
          state_manifest JSONB NOT NULL,
          transition_manifest JSONB NOT NULL,
          invariant_manifest JSONB NOT NULL,
          source_location VARCHAR(500) NOT NULL,
          verification_status VARCHAR(24) NOT NULL DEFAULT 'not_run',
          verification_findings JSONB NOT NULL DEFAULT '[]'::jsonb,
          manifest_checksum_sha256 VARCHAR(64) NOT NULL,
          status VARCHAR(24) NOT NULL DEFAULT 'draft',
          verified_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(machine_code,version),
          CHECK (verification_status IN ('not_run','pass','fail')),
          CHECK (status IN ('draft','active','retired','invalid')),
          CHECK (manifest_checksum_sha256 ~ '^[0-9a-f]{64}$')
        );

        CREATE TABLE process_instances (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          process_number VARCHAR(64) NOT NULL UNIQUE,
          process_definition_id UUID NOT NULL REFERENCES process_definitions(id),
          business_key VARCHAR(255) NOT NULL,
          actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
          source_entity_type VARCHAR(64) NOT NULL,
          source_entity_id UUID,
          current_step_code VARCHAR(128),
          context_encrypted TEXT NOT NULL,
          context_hash VARCHAR(64) NOT NULL,
          status VARCHAR(32) NOT NULL DEFAULT 'created',
          lock_version INTEGER NOT NULL DEFAULT 0,
          deadline_at TIMESTAMPTZ NOT NULL,
          last_progress_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          waiting_for VARCHAR(64),
          final_outcome VARCHAR(64),
          failure_code VARCHAR(128),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          completed_at TIMESTAMPTZ,
          UNIQUE(process_definition_id,business_key),
          CHECK (context_hash ~ '^[0-9a-f]{64}$'),
          CHECK (status IN ('created','running','waiting_user','waiting_other_party','waiting_platform','waiting_provider','waiting_event','paused','cancelling','compensating','manual_intervention','succeeded','failed','cancelled','expired','safety_frozen')),
          CHECK ((status IN ('succeeded','failed','cancelled','expired')) = (completed_at IS NOT NULL))
        );

        CREATE INDEX ix_process_instances_status_progress
          ON process_instances(status,last_progress_at,deadline_at);

        CREATE TABLE process_step_executions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          process_instance_id UUID NOT NULL REFERENCES process_instances(id) ON DELETE CASCADE,
          step_definition_id UUID NOT NULL REFERENCES process_step_definitions(id),
          execution_number INTEGER NOT NULL,
          idempotency_key VARCHAR(255) NOT NULL,
          request_hash VARCHAR(64) NOT NULL,
          command_execution_id UUID NOT NULL DEFAULT gen_random_uuid(),
          status VARCHAR(32) NOT NULL DEFAULT 'pending',
          attempt_count INTEGER NOT NULL DEFAULT 0,
          expected_events JSONB NOT NULL DEFAULT '[]'::jsonb,
          received_events JSONB NOT NULL DEFAULT '[]'::jsonb,
          output_receipt JSONB NOT NULL DEFAULT '{}'::jsonb,
          error_detail JSONB NOT NULL DEFAULT '{}'::jsonb,
          next_retry_at TIMESTAMPTZ,
          timeout_at TIMESTAMPTZ,
          started_at TIMESTAMPTZ,
          completed_at TIMESTAMPTZ,
          UNIQUE(process_instance_id,idempotency_key),
          CHECK (request_hash ~ '^[0-9a-f]{64}$'),
          CHECK (status IN ('pending','running','waiting_event','succeeded','failed','timed_out','cancelled','compensated','compensation_failed'))
        );

        CREATE TABLE process_event_inbox (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          consumer_code VARCHAR(128) NOT NULL,
          event_id UUID NOT NULL,
          event_code VARCHAR(160) NOT NULL,
          aggregate_type VARCHAR(128) NOT NULL,
          aggregate_id UUID NOT NULL,
          aggregate_version BIGINT NOT NULL,
          payload_hash VARCHAR(64) NOT NULL,
          disposition VARCHAR(24) NOT NULL,
          process_instance_id UUID REFERENCES process_instances(id) ON DELETE SET NULL,
          received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(consumer_code,event_id),
          CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
          CHECK (disposition IN ('accepted','duplicate','buffered_future','rejected_old','gap_detected'))
        );

        CREATE TABLE process_compensation_definitions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          compensation_code VARCHAR(128) NOT NULL UNIQUE,
          owning_module VARCHAR(64) NOT NULL,
          target_command_code VARCHAR(160) NOT NULL,
          input_mapping JSONB NOT NULL,
          retry_policy JSONB NOT NULL,
          reversible BOOLEAN NOT NULL,
          human_approval_required BOOLEAN NOT NULL DEFAULT false,
          preserves_irreversible_facts BOOLEAN NOT NULL DEFAULT true,
          active BOOLEAN NOT NULL DEFAULT true,
          CHECK (target_command_code !~* '(delete_payment|mark_unpaid|delete_consent|direct_sql)')
        );

        CREATE TABLE process_compensation_executions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          process_instance_id UUID NOT NULL REFERENCES process_instances(id) ON DELETE CASCADE,
          step_execution_id UUID NOT NULL REFERENCES process_step_executions(id),
          compensation_definition_id UUID NOT NULL REFERENCES process_compensation_definitions(id),
          idempotency_key VARCHAR(255) NOT NULL UNIQUE,
          status VARCHAR(32) NOT NULL DEFAULT 'pending',
          attempt_count INTEGER NOT NULL DEFAULT 0,
          execution_receipt JSONB NOT NULL DEFAULT '{}'::jsonb,
          error_detail JSONB NOT NULL DEFAULT '{}'::jsonb,
          requested_by UUID REFERENCES users(id),
          approved_by UUID REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          completed_at TIMESTAMPTZ,
          CHECK (status IN ('pending','approved','running','succeeded','failed','manual_required')),
          CHECK (approved_by IS NULL OR approved_by<>requested_by)
        );

        CREATE TABLE process_cancellation_requests (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          process_instance_id UUID NOT NULL REFERENCES process_instances(id) ON DELETE CASCADE,
          cancellation_key VARCHAR(255) NOT NULL UNIQUE,
          request_type VARCHAR(32) NOT NULL,
          reason_code VARCHAR(128) NOT NULL,
          requested_by UUID REFERENCES users(id),
          expected_lock_version INTEGER NOT NULL,
          status VARCHAR(24) NOT NULL DEFAULT 'requested',
          rejection_code VARCHAR(128),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          completed_at TIMESTAMPTZ,
          CHECK (request_type IN ('user','system','admin_technical','safety','provider')),
          CHECK (status IN ('requested','accepted','rejected','completed'))
        );

        CREATE TABLE process_stuck_findings (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          finding_code VARCHAR(255) NOT NULL UNIQUE,
          process_instance_id UUID NOT NULL REFERENCES process_instances(id) ON DELETE CASCADE,
          finding_type VARCHAR(64) NOT NULL,
          severity VARCHAR(16) NOT NULL,
          evidence JSONB NOT NULL,
          status VARCHAR(24) NOT NULL DEFAULT 'open',
          detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          resolved_at TIMESTAMPTZ,
          CHECK (severity IN ('low','medium','high','critical')),
          CHECK (status IN ('open','acknowledged','resolved','false_positive'))
        );

        CREATE TABLE process_intervention_tasks (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          process_instance_id UUID NOT NULL REFERENCES process_instances(id) ON DELETE CASCADE,
          stuck_finding_id UUID REFERENCES process_stuck_findings(id),
          priority VARCHAR(16) NOT NULL,
          allowed_resolution_commands JSONB NOT NULL,
          assigned_to UUID REFERENCES users(id),
          due_at TIMESTAMPTZ NOT NULL,
          status VARCHAR(24) NOT NULL DEFAULT 'open',
          resolution_command VARCHAR(160),
          resolution_receipt JSONB NOT NULL DEFAULT '{}'::jsonb,
          resolved_by UUID REFERENCES users(id),
          resolved_at TIMESTAMPTZ,
          CHECK (priority IN ('low','medium','high','critical')),
          CHECK (status IN ('open','assigned','resolved','rejected')),
          CHECK (resolution_command IS NULL OR resolution_command !~* '(direct_sql|set_state|fabricate)')
        );

        CREATE TABLE process_simulation_runs (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          scenario_code VARCHAR(128) NOT NULL,
          process_code VARCHAR(128) NOT NULL,
          synthetic_seed BIGINT NOT NULL,
          virtual_clock_start TIMESTAMPTZ NOT NULL,
          fault_manifest JSONB NOT NULL,
          expected_outcome JSONB NOT NULL,
          observed_outcome JSONB NOT NULL,
          invariant_results JSONB NOT NULL,
          status VARCHAR(24) NOT NULL,
          run_by UUID REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (status IN ('pass','fail','not_run'))
        );

        CREATE TABLE process_domain_certifications (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          business_domain VARCHAR(64) NOT NULL,
          git_commit VARCHAR(64) NOT NULL,
          environment VARCHAR(32) NOT NULL,
          path_results JSONB NOT NULL,
          unresolved_critical_stuck INTEGER NOT NULL DEFAULT 0,
          technical_status VARCHAR(24) NOT NULL,
          production_status VARCHAR(24) NOT NULL DEFAULT 'not_certified',
          evidence_checksum_sha256 VARCHAR(64) NOT NULL,
          evaluated_by UUID REFERENCES users(id),
          certified_by UUID REFERENCES users(id),
          evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          certified_at TIMESTAMPTZ,
          UNIQUE(business_domain,git_commit,environment),
          CHECK (technical_status IN ('pass','fail','not_run')),
          CHECK (production_status IN ('not_certified','certified','rejected')),
          CHECK (unresolved_critical_stuck >= 0),
          CHECK (evidence_checksum_sha256 ~ '^[0-9a-f]{64}$'),
          CHECK (certified_by IS NULL OR certified_by<>evaluated_by)
        );
        """
    )


def downgrade() -> None:
    _run(
        """
        DROP TABLE process_domain_certifications;
        DROP TABLE process_simulation_runs;
        DROP TABLE process_intervention_tasks;
        DROP TABLE process_stuck_findings;
        DROP TABLE process_cancellation_requests;
        DROP TABLE process_compensation_executions;
        DROP TABLE process_compensation_definitions;
        DROP TABLE process_event_inbox;
        DROP TABLE process_step_executions;
        DROP TABLE process_instances;
        DROP TABLE state_machine_definitions;
        DROP TABLE process_step_definitions;
        DROP TABLE process_definitions;
        """
    )
