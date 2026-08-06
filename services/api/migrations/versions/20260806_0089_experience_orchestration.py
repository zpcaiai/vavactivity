"""Create the Batch 23 experience-orchestration control plane.

Revision ID: 20260806_0089
Revises: 20260806_0088
"""

# ruff: noqa: E501

from alembic import op

revision = "20260806_0089"
down_revision = "20260806_0088"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(
        """
        CREATE TABLE experience_ia_versions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          version VARCHAR(64) NOT NULL UNIQUE,
          status VARCHAR(32) NOT NULL DEFAULT 'draft',
          manifest_checksum_sha256 VARCHAR(64) NOT NULL,
          activated_by UUID REFERENCES users(id),
          activated_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (status IN ('draft','active','retired','rejected')),
          CHECK (manifest_checksum_sha256 ~ '^[0-9a-f]{64}$')
        );

        CREATE UNIQUE INDEX uq_experience_one_active_ia
          ON experience_ia_versions ((status)) WHERE status='active';

        CREATE TABLE experience_ia_nodes (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          ia_version_id UUID NOT NULL REFERENCES experience_ia_versions(id) ON DELETE CASCADE,
          node_code VARCHAR(128) NOT NULL,
          parent_node_code VARCHAR(128),
          space VARCHAR(64) NOT NULL,
          localized_labels JSONB NOT NULL,
          primary_route_code VARCHAR(128),
          secondary_route_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
          lifecycle VARCHAR(32) NOT NULL DEFAULT 'active',
          sort_order INTEGER NOT NULL DEFAULT 0,
          UNIQUE(ia_version_id,node_code),
          CHECK (space IN ('public','account','services','matchmaking','safety_privacy','admin','skill_console')),
          CHECK (lifecycle IN ('active','deprecated','retired'))
        );

        CREATE TABLE experience_routes (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          route_code VARCHAR(128) NOT NULL UNIQUE,
          application_code VARCHAR(64) NOT NULL,
          route_name VARCHAR(128) NOT NULL,
          route_path VARCHAR(500) NOT NULL,
          page_code VARCHAR(128) NOT NULL,
          ia_node_code VARCHAR(128) NOT NULL,
          route_type VARCHAR(32) NOT NULL DEFAULT 'page',
          authentication_required BOOLEAN NOT NULL DEFAULT false,
          permission_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
          capability_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
          feature_flag VARCHAR(128),
          prerequisite_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
          fallback_route_code VARCHAR(128),
          breadcrumb_policy JSONB NOT NULL DEFAULT '[]'::jsonb,
          help_context_code VARCHAR(128),
          lifecycle VARCHAR(32) NOT NULL DEFAULT 'active',
          critical BOOLEAN NOT NULL DEFAULT false,
          sort_order INTEGER NOT NULL DEFAULT 0,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (application_code IN ('user-web','admin-web','skill-console')),
          CHECK (route_type IN ('page','status','action','redirect')),
          CHECK (lifecycle IN ('active','deprecated','retired')),
          CHECK (route_path LIKE '/%'),
          CHECK (route_path !~* '(phone|email|evidence|price)=')
        );

        CREATE INDEX ix_experience_routes_app_node
          ON experience_routes(application_code,ia_node_code,lifecycle);

        CREATE TABLE experience_task_definitions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          task_code VARCHAR(128) NOT NULL,
          version INTEGER NOT NULL DEFAULT 1,
          source_module VARCHAR(64) NOT NULL,
          title_i18n JSONB NOT NULL,
          description_i18n JSONB NOT NULL,
          priority INTEGER NOT NULL,
          due_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
          completion_policy JSONB NOT NULL,
          action_route_code VARCHAR(128) NOT NULL,
          fallback_route_code VARCHAR(128) NOT NULL,
          visibility_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
          active BOOLEAN NOT NULL DEFAULT true,
          UNIQUE(task_code,version),
          CHECK (priority BETWEEN 0 AND 1000)
        );

        CREATE TABLE experience_user_tasks (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          task_definition_id UUID NOT NULL REFERENCES experience_task_definitions(id),
          source_module VARCHAR(64) NOT NULL,
          source_entity_type VARCHAR(64) NOT NULL,
          source_entity_id UUID,
          deduplication_key VARCHAR(255) NOT NULL,
          state VARCHAR(32) NOT NULL DEFAULT 'available',
          priority INTEGER NOT NULL,
          due_at TIMESTAMPTZ,
          authoritative_state_version VARCHAR(128) NOT NULL,
          invalidated_at TIMESTAMPTZ,
          completed_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(user_id,deduplication_key),
          CHECK (state IN ('available','in_progress','waiting_user','waiting_other_party','waiting_platform','waiting_provider','completed','expired','invalidated'))
        );

        CREATE INDEX ix_experience_tasks_user_state
          ON experience_user_tasks(user_id,state,priority DESC,due_at);

        CREATE TABLE experience_journey_definitions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          journey_code VARCHAR(128) NOT NULL,
          version INTEGER NOT NULL,
          actor_type VARCHAR(32) NOT NULL DEFAULT 'user',
          step_manifest JSONB NOT NULL,
          transition_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
          completion_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
          cancellation_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
          status VARCHAR(32) NOT NULL DEFAULT 'draft',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          activated_at TIMESTAMPTZ,
          UNIQUE(journey_code,version),
          CHECK (status IN ('draft','active','retired'))
        );

        CREATE TABLE experience_journey_instances (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          definition_id UUID NOT NULL REFERENCES experience_journey_definitions(id),
          user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          source_module VARCHAR(64) NOT NULL,
          source_entity_type VARCHAR(64),
          source_entity_id UUID,
          current_step_code VARCHAR(128) NOT NULL,
          context_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
          authoritative_state_version VARCHAR(128) NOT NULL,
          state VARCHAR(32) NOT NULL DEFAULT 'active',
          block_reason_code VARCHAR(128),
          started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          completed_at TIMESTAMPTZ,
          CHECK (state IN ('active','blocked','waiting','completed','cancelled','expired','invalidated'))
        );

        CREATE INDEX ix_experience_journeys_user_state
          ON experience_journey_instances(user_id,state,updated_at DESC);

        CREATE TABLE experience_handoff_definitions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          handoff_code VARCHAR(128) NOT NULL UNIQUE,
          source_module VARCHAR(64) NOT NULL,
          target_module VARCHAR(64) NOT NULL,
          context_schema JSONB NOT NULL,
          prerequisite_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
          completion_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
          return_route_code VARCHAR(128) NOT NULL,
          failure_route_code VARCHAR(128) NOT NULL,
          ttl_seconds INTEGER NOT NULL DEFAULT 900,
          active BOOLEAN NOT NULL DEFAULT true,
          CHECK (ttl_seconds BETWEEN 60 AND 86400)
        );

        CREATE TABLE experience_handoff_instances (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          definition_id UUID NOT NULL REFERENCES experience_handoff_definitions(id),
          user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          source_entity_type VARCHAR(64) NOT NULL,
          source_entity_id UUID NOT NULL,
          target_entity_type VARCHAR(64),
          target_entity_id UUID,
          user_intent VARCHAR(128) NOT NULL,
          context_encrypted TEXT NOT NULL,
          context_hash VARCHAR(64) NOT NULL,
          source_route_code VARCHAR(128) NOT NULL,
          target_route_code VARCHAR(128) NOT NULL,
          return_route_code VARCHAR(128) NOT NULL,
          state VARCHAR(32) NOT NULL DEFAULT 'pending',
          expires_at TIMESTAMPTZ NOT NULL,
          completed_at TIMESTAMPTZ,
          failure_code VARCHAR(128),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (context_hash ~ '^[0-9a-f]{64}$'),
          CHECK (state IN ('pending','accepted','completed','failed','expired','invalidated'))
        );

        CREATE INDEX ix_experience_handoffs_user_state
          ON experience_handoff_instances(user_id,state,expires_at);

        CREATE TABLE experience_search_documents (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          document_code VARCHAR(255) NOT NULL UNIQUE,
          source_module VARCHAR(64) NOT NULL,
          source_entity_type VARCHAR(64) NOT NULL,
          source_entity_id UUID,
          title VARCHAR(500) NOT NULL,
          summary TEXT NOT NULL DEFAULT '',
          locale VARCHAR(16) NOT NULL,
          visibility VARCHAR(32) NOT NULL,
          permission_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
          owner_user_id UUID REFERENCES users(id) ON DELETE CASCADE,
          route_code VARCHAR(128) NOT NULL,
          route_parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
          source_version VARCHAR(128) NOT NULL,
          index_status VARCHAR(32) NOT NULL DEFAULT 'active',
          blocked BOOLEAN NOT NULL DEFAULT false,
          erased BOOLEAN NOT NULL DEFAULT false,
          search_vector TSVECTOR GENERATED ALWAYS AS
            (to_tsvector('simple',coalesce(title,'') || ' ' || coalesce(summary,''))) STORED,
          indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (visibility IN ('public','personal','admin')),
          CHECK (index_status IN ('active','stale','removed')),
          CHECK (source_entity_type NOT IN ('one_sided_like','private_reflection','safety_evidence','payment_secret'))
        );

        CREATE INDEX ix_experience_search_vector
          ON experience_search_documents USING GIN(search_vector);
        CREATE INDEX ix_experience_search_visibility
          ON experience_search_documents(visibility,owner_user_id,index_status);

        CREATE TABLE experience_help_articles (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          article_code VARCHAR(128) NOT NULL,
          version INTEGER NOT NULL,
          category VARCHAR(64) NOT NULL,
          route_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
          state_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
          actor_types JSONB NOT NULL DEFAULT '[]'::jsonb,
          locale VARCHAR(16) NOT NULL,
          title VARCHAR(500) NOT NULL,
          body_markdown TEXT NOT NULL,
          status VARCHAR(32) NOT NULL DEFAULT 'draft',
          published_at TIMESTAMPTZ,
          retired_at TIMESTAMPTZ,
          UNIQUE(article_code,version,locale),
          CHECK (status IN ('draft','published','retired'))
        );

        CREATE TABLE experience_support_requests (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          source_route_code VARCHAR(128) NOT NULL,
          source_entity_type VARCHAR(64),
          source_entity_id UUID,
          category VARCHAR(64) NOT NULL,
          description_encrypted TEXT NOT NULL,
          assignment_queue VARCHAR(64) NOT NULL,
          state VARCHAR(32) NOT NULL DEFAULT 'open',
          assigned_to UUID REFERENCES users(id),
          resolved_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (category IN ('general','safety','privacy','payment_dispute','broken_link','unclear_status')),
          CHECK (state IN ('open','assigned','resolved','closed'))
        );

        CREATE TABLE experience_feedback (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id UUID REFERENCES users(id) ON DELETE SET NULL,
          route_code VARCHAR(128) NOT NULL,
          feedback_type VARCHAR(64) NOT NULL,
          context_minimized JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (feedback_type IN ('cannot_find_next_step','unclear_explanation','broken_page','incorrect_status','broken_link','unhelpful_help'))
        );

        CREATE TABLE experience_deep_links (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          purpose VARCHAR(128) NOT NULL,
          token_hash VARCHAR(64) NOT NULL UNIQUE,
          user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          entity_type VARCHAR(64) NOT NULL,
          entity_id UUID NOT NULL,
          target_route_code VARCHAR(128) NOT NULL,
          fallback_route_code VARCHAR(128) NOT NULL,
          route_parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
          permission_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
          single_use BOOLEAN NOT NULL DEFAULT true,
          expires_at TIMESTAMPTZ NOT NULL,
          consumed_at TIMESTAMPTZ,
          invalidated_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (token_hash ~ '^[0-9a-f]{64}$')
        );

        CREATE TABLE experience_dead_end_findings (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          finding_code VARCHAR(255) NOT NULL UNIQUE,
          finding_type VARCHAR(64) NOT NULL,
          route_code VARCHAR(128),
          severity VARCHAR(32) NOT NULL,
          owner_team VARCHAR(128) NOT NULL,
          evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
          status VARCHAR(32) NOT NULL DEFAULT 'open',
          detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          resolved_at TIMESTAMPTZ,
          resolved_by UUID REFERENCES users(id),
          CHECK (severity IN ('low','medium','high','critical')),
          CHECK (status IN ('open','acknowledged','resolved','false_positive'))
        );

        CREATE TABLE experience_analytics_events (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_pseudonym VARCHAR(64),
          journey_code VARCHAR(128),
          journey_instance_id UUID REFERENCES experience_journey_instances(id) ON DELETE SET NULL,
          event_type VARCHAR(64) NOT NULL,
          step_code VARCHAR(128),
          safe_dimensions JSONB NOT NULL DEFAULT '{}'::jsonb,
          occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (event_type IN ('journey_started','step_viewed','step_started','step_completed','step_failed','step_abandoned','journey_blocked','journey_resumed','journey_completed','journey_cancelled'))
        );

        CREATE TABLE experience_closure_checks (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          capability_code VARCHAR(128) NOT NULL,
          git_commit VARCHAR(64) NOT NULL,
          environment VARCHAR(32) NOT NULL,
          checks JSONB NOT NULL,
          technical_status VARCHAR(32) NOT NULL,
          production_status VARCHAR(32) NOT NULL DEFAULT 'not_certified',
          evidence_checksum_sha256 VARCHAR(64) NOT NULL,
          evaluated_by UUID REFERENCES users(id),
          certified_by UUID REFERENCES users(id),
          evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          certified_at TIMESTAMPTZ,
          certification_reason TEXT,
          UNIQUE(capability_code,git_commit,environment),
          CHECK (technical_status IN ('pass','fail','not_run')),
          CHECK (production_status IN ('not_certified','certified','rejected')),
          CHECK (evidence_checksum_sha256 ~ '^[0-9a-f]{64}$'),
          CHECK (certified_by IS NULL OR certified_by<>evaluated_by)
        );

        CREATE INDEX ix_experience_dead_end_status
          ON experience_dead_end_findings(severity,status);
        CREATE INDEX ix_experience_analytics_journey
          ON experience_analytics_events(journey_code,event_type,occurred_at);
        """
    )


def downgrade() -> None:
    _run(
        """
        DROP TABLE experience_closure_checks;
        DROP TABLE experience_analytics_events;
        DROP TABLE experience_dead_end_findings;
        DROP TABLE experience_deep_links;
        DROP TABLE experience_feedback;
        DROP TABLE experience_support_requests;
        DROP TABLE experience_help_articles;
        DROP TABLE experience_search_documents;
        DROP TABLE experience_handoff_instances;
        DROP TABLE experience_handoff_definitions;
        DROP TABLE experience_journey_instances;
        DROP TABLE experience_journey_definitions;
        DROP TABLE experience_user_tasks;
        DROP TABLE experience_task_definitions;
        DROP TABLE experience_routes;
        DROP TABLE experience_ia_nodes;
        DROP TABLE experience_ia_versions;
        """
    )
