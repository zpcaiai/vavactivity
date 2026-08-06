"""Create the Batch 21 quality governance control plane.

Revision ID: 20260806_0087
Revises: 20260806_0086
"""

from alembic import op

revision = "20260806_0087"
down_revision = "20260806_0086"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(
        """
        CREATE TABLE quality_requirements (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          requirement_code VARCHAR(128) NOT NULL UNIQUE,
          title VARCHAR(500) NOT NULL,
          description TEXT NOT NULL,
          source_type VARCHAR(64) NOT NULL,
          source_reference VARCHAR(1000),
          source_version VARCHAR(64),
          requirement_type VARCHAR(64) NOT NULL,
          business_domain VARCHAR(64) NOT NULL,
          criticality VARCHAR(32) NOT NULL,
          status VARCHAR(32) NOT NULL,
          acceptance_criteria JSONB NOT NULL,
          non_functional_criteria JSONB NOT NULL DEFAULT '{}'::jsonb,
          owner_team VARCHAR(128) NOT NULL,
          owner_user_id UUID REFERENCES users(id),
          parent_requirement_id UUID REFERENCES quality_requirements(id),
          introduced_in_batch INTEGER,
          target_release VARCHAR(64),
          created_by UUID NOT NULL REFERENCES users(id),
          approved_by UUID REFERENCES users(id),
          content_fingerprint VARCHAR(64) NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          approved_at TIMESTAMPTZ,
          CHECK (criticality IN ('blocker','critical','major','normal','minor')),
          CHECK (
            status IN (
              'draft','approved','in_implementation','implemented','verified',
              'deferred','rejected','superseded'
            )
          ),
          CHECK (approved_by IS NULL OR approved_by<>created_by)
        );

        CREATE TABLE quality_capabilities (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          capability_code VARCHAR(128) NOT NULL UNIQUE,
          name VARCHAR(300) NOT NULL,
          description TEXT NOT NULL,
          capability_type VARCHAR(64) NOT NULL,
          module_code VARCHAR(64) NOT NULL,
          criticality VARCHAR(32) NOT NULL,
          lifecycle_status VARCHAR(32) NOT NULL,
          owning_service VARCHAR(128),
          primary_actor_type VARCHAR(64),
          introduced_in_batch INTEGER,
          current_version VARCHAR(64),
          owner_team VARCHAR(128) NOT NULL,
          created_by UUID NOT NULL REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (
            lifecycle_status IN (
              'planned','in_development','available','suspended',
              'deprecated','retired','cancelled'
            )
          )
        );

        CREATE TABLE quality_trace_nodes (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          node_type VARCHAR(64) NOT NULL,
          node_code VARCHAR(255) NOT NULL,
          module_code VARCHAR(64),
          title VARCHAR(500) NOT NULL,
          source_location VARCHAR(1000),
          version VARCHAR(64) NOT NULL DEFAULT '1.0.0',
          status VARCHAR(32) NOT NULL,
          metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(node_type,node_code,version)
        );

        CREATE TABLE quality_trace_links (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          source_node_id UUID NOT NULL REFERENCES quality_trace_nodes(id) ON DELETE CASCADE,
          target_node_id UUID NOT NULL REFERENCES quality_trace_nodes(id) ON DELETE CASCADE,
          relationship_type VARCHAR(64) NOT NULL,
          required BOOLEAN NOT NULL DEFAULT true,
          status VARCHAR(32) NOT NULL,
          verification_method VARCHAR(64),
          verified_by UUID REFERENCES users(id),
          verified_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(source_node_id,target_node_id,relationship_type),
          CHECK (source_node_id<>target_node_id)
        );

        CREATE TABLE quality_pages (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          application_code VARCHAR(64) NOT NULL,
          route_name VARCHAR(255) NOT NULL,
          route_path VARCHAR(500) NOT NULL,
          page_type VARCHAR(64) NOT NULL,
          actor_types JSONB NOT NULL,
          feature_flag_code VARCHAR(128),
          required_permissions JSONB NOT NULL DEFAULT '[]'::jsonb,
          source_location VARCHAR(1000) NOT NULL,
          status VARCHAR(32) NOT NULL,
          scan_fingerprint VARCHAR(64) NOT NULL,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(application_code,route_name)
        );

        CREATE TABLE quality_api_operations (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          operation_id VARCHAR(255) NOT NULL UNIQUE,
          method VARCHAR(8) NOT NULL,
          path VARCHAR(1000) NOT NULL,
          module_code VARCHAR(64),
          request_schema JSONB,
          response_schema JSONB,
          permissions JSONB NOT NULL DEFAULT '[]'::jsonb,
          error_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
          idempotency_requirement VARCHAR(64),
          internal_purpose TEXT,
          scan_fingerprint VARCHAR(64) NOT NULL,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(method,path)
        );

        CREATE TABLE quality_business_flows (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          flow_code VARCHAR(128) NOT NULL UNIQUE,
          name VARCHAR(300) NOT NULL,
          business_domain VARCHAR(64) NOT NULL,
          criticality VARCHAR(32) NOT NULL,
          primary_actor_type VARCHAR(64) NOT NULL,
          supporting_actor_types JSONB NOT NULL DEFAULT '[]'::jsonb,
          start_condition JSONB NOT NULL,
          success_end_conditions JSONB NOT NULL,
          failure_end_conditions JSONB NOT NULL,
          cancellation_conditions JSONB NOT NULL DEFAULT '[]'::jsonb,
          closure_checks JSONB NOT NULL,
          manual_intervention_supported BOOLEAN NOT NULL,
          compensation_required BOOLEAN NOT NULL,
          owner_team VARCHAR(128) NOT NULL,
          status VARCHAR(32) NOT NULL,
          certified_by UUID REFERENCES users(id),
          certified_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE quality_business_flow_steps (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          business_flow_id UUID NOT NULL REFERENCES quality_business_flows(id) ON DELETE CASCADE,
          step_code VARCHAR(128) NOT NULL,
          sequence_number INTEGER NOT NULL CHECK (sequence_number>0),
          capability_code VARCHAR(128) NOT NULL,
          preconditions JSONB NOT NULL,
          postconditions JSONB NOT NULL,
          possible_errors JSONB NOT NULL DEFAULT '[]'::jsonb,
          compensation_step_code VARCHAR(128),
          user_visible_state VARCHAR(128),
          admin_visible_state VARCHAR(128),
          UNIQUE(business_flow_id,step_code),
          UNIQUE(business_flow_id,sequence_number)
        );

        CREATE TABLE quality_exception_scenarios (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          scenario_code VARCHAR(128) NOT NULL UNIQUE,
          business_flow_id UUID NOT NULL REFERENCES quality_business_flows(id) ON DELETE CASCADE,
          exception_type VARCHAR(64) NOT NULL,
          trigger_condition JSONB NOT NULL,
          expected_business_state VARCHAR(128) NOT NULL,
          expected_user_message_code VARCHAR(128),
          expected_admin_action VARCHAR(128),
          compensation_expected BOOLEAN NOT NULL,
          retry_expected BOOLEAN NOT NULL,
          criticality VARCHAR(32) NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE quality_gaps (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          gap_code VARCHAR(128) NOT NULL UNIQUE,
          gap_type VARCHAR(64) NOT NULL,
          severity VARCHAR(32) NOT NULL,
          source_node_id UUID REFERENCES quality_trace_nodes(id),
          description TEXT NOT NULL,
          detection_rule_code VARCHAR(128) NOT NULL,
          status VARCHAR(32) NOT NULL,
          owner_team VARCHAR(128),
          owner_user_id UUID REFERENCES users(id),
          detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          resolved_at TIMESTAMPTZ,
          resolution_summary TEXT,
          waiver_id UUID
        );

        CREATE TABLE quality_risks (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          risk_code VARCHAR(128) NOT NULL UNIQUE,
          title VARCHAR(500) NOT NULL,
          description TEXT NOT NULL,
          category VARCHAR(64) NOT NULL,
          severity VARCHAR(32) NOT NULL,
          likelihood VARCHAR(32) NOT NULL,
          affected_requirements JSONB NOT NULL,
          affected_capabilities JSONB NOT NULL,
          mitigation_plan TEXT,
          contingency_plan TEXT,
          owner_user_id UUID REFERENCES users(id),
          owner_team VARCHAR(128) NOT NULL,
          status VARCHAR(32) NOT NULL,
          target_resolution_date DATE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE quality_gate_definitions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          gate_code VARCHAR(128) NOT NULL,
          semantic_version VARCHAR(64) NOT NULL,
          name VARCHAR(300) NOT NULL,
          category VARCHAR(64) NOT NULL,
          enforcement_level VARCHAR(32) NOT NULL,
          condition_definition JSONB NOT NULL,
          required_evidence_types JSONB NOT NULL,
          applicable_release_types JSONB NOT NULL,
          applicable_modules JSONB NOT NULL DEFAULT '[]'::jsonb,
          status VARCHAR(32) NOT NULL,
          created_by UUID NOT NULL REFERENCES users(id),
          approved_by UUID REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          approved_at TIMESTAMPTZ,
          UNIQUE(gate_code,semantic_version),
          CHECK (enforcement_level IN ('blocker','required','advisory')),
          CHECK (approved_by IS NULL OR approved_by<>created_by)
        );

        CREATE TABLE quality_waivers (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          waiver_number VARCHAR(64) NOT NULL UNIQUE,
          gate_definition_id UUID REFERENCES quality_gate_definitions(id),
          quality_gap_id UUID REFERENCES quality_gaps(id),
          quality_risk_id UUID REFERENCES quality_risks(id),
          justification TEXT NOT NULL,
          mitigation_conditions JSONB NOT NULL,
          scope JSONB NOT NULL,
          status VARCHAR(32) NOT NULL,
          requested_by UUID NOT NULL REFERENCES users(id),
          approved_by UUID REFERENCES users(id),
          valid_from TIMESTAMPTZ NOT NULL,
          expires_at TIMESTAMPTZ NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          approved_at TIMESTAMPTZ,
          revoked_at TIMESTAMPTZ,
          CHECK (expires_at>valid_from),
          CHECK (approved_by IS NULL OR approved_by<>requested_by)
        );
        ALTER TABLE quality_gaps
          ADD CONSTRAINT fk_quality_gaps_waiver
          FOREIGN KEY (waiver_id) REFERENCES quality_waivers(id);

        CREATE TABLE quality_evidence (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          evidence_code VARCHAR(128) NOT NULL UNIQUE,
          evidence_type VARCHAR(64) NOT NULL,
          title VARCHAR(500) NOT NULL,
          source_system VARCHAR(64) NOT NULL,
          source_reference VARCHAR(1000),
          release_version VARCHAR(64) NOT NULL,
          git_commit VARCHAR(64) NOT NULL,
          environment VARCHAR(32) NOT NULL,
          status VARCHAR(32) NOT NULL,
          artifact_reference_encrypted TEXT,
          artifact_checksum_sha256 VARCHAR(64),
          summary JSONB NOT NULL,
          generated_at TIMESTAMPTZ NOT NULL,
          expires_at TIMESTAMPTZ,
          registered_by UUID NOT NULL REFERENCES users(id),
          validated_by UUID REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (validated_by IS NULL OR validated_by<>registered_by)
        );

        CREATE TABLE quality_gate_runs (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          gate_definition_id UUID NOT NULL REFERENCES quality_gate_definitions(id),
          release_version VARCHAR(64) NOT NULL,
          git_commit VARCHAR(64) NOT NULL,
          environment VARCHAR(32) NOT NULL,
          status VARCHAR(32) NOT NULL,
          evaluated_value JSONB,
          expected_condition JSONB NOT NULL,
          evidence_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
          failure_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
          waiver_id UUID REFERENCES quality_waivers(id),
          started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          completed_at TIMESTAMPTZ,
          triggered_by UUID REFERENCES users(id),
          UNIQUE(gate_definition_id,release_version,environment)
        );

        CREATE TABLE quality_release_evaluations (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          release_version VARCHAR(64) NOT NULL,
          git_commit VARCHAR(64) NOT NULL,
          environment VARCHAR(32) NOT NULL,
          decision VARCHAR(32) NOT NULL,
          structural_score NUMERIC(5,2),
          gate_run_ids JSONB NOT NULL,
          failure_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
          evaluated_by UUID NOT NULL REFERENCES users(id),
          evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(release_version,environment),
          CHECK (decision IN ('go','conditional_go','no_go'))
        );

        CREATE TABLE quality_certifications (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          release_evaluation_id UUID NOT NULL UNIQUE REFERENCES quality_release_evaluations(id),
          certification_status VARCHAR(32) NOT NULL,
          evidence_manifest JSONB NOT NULL,
          certified_by UUID NOT NULL REFERENCES users(id),
          certified_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (certification_status IN ('not_certified','conditionally_certified','certified'))
        );

        CREATE INDEX ix_quality_requirements_status_criticality
          ON quality_requirements(status,criticality);
        CREATE INDEX ix_quality_trace_nodes_type_module
          ON quality_trace_nodes(node_type,module_code);
        CREATE INDEX ix_quality_gaps_status_severity ON quality_gaps(status,severity);
        CREATE INDEX ix_quality_gate_runs_release_status
          ON quality_gate_runs(release_version,status);
        CREATE INDEX ix_quality_evidence_release_status ON quality_evidence(release_version,status);
        """
    )


def downgrade() -> None:
    _run(
        """
        DROP TABLE quality_certifications;
        DROP TABLE quality_release_evaluations;
        DROP TABLE quality_gate_runs;
        DROP TABLE quality_evidence;
        ALTER TABLE quality_gaps DROP CONSTRAINT fk_quality_gaps_waiver;
        DROP TABLE quality_waivers;
        DROP TABLE quality_gate_definitions;
        DROP TABLE quality_risks;
        DROP TABLE quality_gaps;
        DROP TABLE quality_exception_scenarios;
        DROP TABLE quality_business_flow_steps;
        DROP TABLE quality_business_flows;
        DROP TABLE quality_api_operations;
        DROP TABLE quality_pages;
        DROP TABLE quality_trace_links;
        DROP TABLE quality_trace_nodes;
        DROP TABLE quality_capabilities;
        DROP TABLE quality_requirements;
        """
    )
