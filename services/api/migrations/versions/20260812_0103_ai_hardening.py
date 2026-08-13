# ruff: noqa: E501

"""AI provider catalogue, enforceable budgets, policy audit, crisis routing and launch gates.

Covers AI-001.

Three things this schema enforces that application code alone could not:

* ``ai_usage_entries`` carries a UNIQUE ``idempotency_key``, so a retried
  request cannot be charged twice against a budget.
* ``ai_crisis_resources`` carries a CHECK that an ``is_active`` row must have a
  ``verified_by`` and a ``verified_at``. An unverified crisis number therefore
  cannot go live even by direct SQL, and the routing code falls back to a human.
* ``ai_launch_gates`` has no seeded rows and no default of ``true``. An absent
  gate reads as unmet, so a deployment cannot inherit a launch claim.

Three tables ship **empty on purpose** and no migration fills them:
``ai_crisis_resources`` (no invented hotline numbers), ``ai_content_policy_rules``
(no invented content-policy text) and ``ai_escalation_runbooks`` (the runbook is
an operational document, not a code artefact). Until an operator fills them, the
crisis path escalates to a human and the launch-readiness endpoint reports the
gaps by name.

``ai_conversations``, ``ai_messages``, ``ai_safety_policies``, ``ai_model_profiles``
and ``ai_model_routes`` already exist and are not redefined here. The columns
below reference conversations by id without a foreign key so this module can be
deployed and rolled back independently of the assistant module's own schema.

Revision ID: 20260812_0103
Revises: 20260812_0102
"""

import re

from alembic import op

revision = "20260812_0103"
down_revision = "20260812_0102"
branch_labels = None
depends_on = None


def _split_statements(script: str) -> list[str]:
    """Split a SQL script on statement boundaries.

    A naive ``script.split(";")`` breaks on any semicolon, including ones
    inside a ``--`` comment or a string literal — which silently turns the
    remainder of a comment into a bogus statement. Postgres then fails on
    something like ``syntax error at or near "it"``, pointing at a line that
    looks perfectly fine.

    This walks the script instead, skipping over line comments, block
    comments, single-quoted strings and dollar-quoted bodies.
    """

    statements: list[str] = []
    buffer: list[str] = []
    index = 0
    length = len(script)
    while index < length:
        char = script[index]
        pair = script[index : index + 2]
        if pair == "--":
            end = script.find("\n", index)
            index = length if end == -1 else end
            continue
        if pair == "/*":
            end = script.find("*/", index + 2)
            index = length if end == -1 else end + 2
            continue
        if char == "'":
            buffer.append(char)
            index += 1
            while index < length:
                buffer.append(script[index])
                if script[index] == "'":
                    if script[index : index + 2] == "''":
                        buffer.append(script[index + 1])
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        if char == "$":
            match = re.match(r"\$[A-Za-z_]*\$", script[index:])
            if match:
                tag = match.group(0)
                end = script.find(tag, index + len(tag))
                stop = length if end == -1 else end + len(tag)
                buffer.append(script[index:stop])
                index = stop
                continue
        if char == ";":
            statements.append("".join(buffer))
            buffer = []
            index += 1
            continue
        buffer.append(char)
        index += 1
    statements.append("".join(buffer))
    return [item.strip() for item in statements if item.strip()]


def _run(script: str) -> None:
    for statement in _split_statements(script):
        op.execute(statement)


def upgrade() -> None:
    _run(
        """
        -- The callable catalogue with the cost and limit columns the budget
        -- arithmetic needs. Costs are integer millicents per 1000 tokens:
        -- floating-point money in a spend limit makes the limit advisory.
        CREATE TABLE ai_provider_profiles (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          provider_code VARCHAR(64) NOT NULL,
          model_code VARCHAR(128) NOT NULL,
          input_cost_per_1k_millicents INTEGER NOT NULL DEFAULT 0,
          output_cost_per_1k_millicents INTEGER NOT NULL DEFAULT 0,
          max_context_tokens INTEGER NOT NULL,
          max_output_tokens INTEGER NOT NULL,
          priority INTEGER NOT NULL DEFAULT 100,
          is_enabled BOOLEAN NOT NULL DEFAULT false,
          capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
          model_profile_id UUID,
          created_by UUID REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (provider_code, model_code),
          CHECK (input_cost_per_1k_millicents >= 0),
          CHECK (output_cost_per_1k_millicents >= 0),
          CHECK (max_context_tokens > 0),
          CHECK (max_output_tokens > 0),
          CHECK (jsonb_typeof(capabilities) = 'array')
        );

        -- Circuit-breaker state. A provider that keeps failing is skipped
        -- rather than retried into a timeout on every member request.
        CREATE TABLE ai_provider_health (
          provider_code VARCHAR(64) PRIMARY KEY,
          status VARCHAR(16) NOT NULL DEFAULT 'healthy',
          consecutive_failures INTEGER NOT NULL DEFAULT 0,
          last_success_at TIMESTAMPTZ,
          last_failure_at TIMESTAMPTZ,
          circuit_opened_at TIMESTAMPTZ,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (status IN ('healthy','degraded','out_of_service')),
          CHECK (consecutive_failures >= 0),
          CHECK (status <> 'out_of_service' OR circuit_opened_at IS NOT NULL)
        );

        -- One row per scope. An absent row means "not configured", which the
        -- domain treats as a refusal, not as unlimited.
        CREATE TABLE ai_budget_policies (
          scope VARCHAR(24) PRIMARY KEY,
          limit_tokens BIGINT,
          limit_millicents BIGINT,
          is_active BOOLEAN NOT NULL DEFAULT true,
          updated_by UUID REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (scope IN ('user_daily','conversation','global_monthly')),
          CHECK (limit_tokens IS NULL OR limit_tokens >= 0),
          CHECK (limit_millicents IS NULL OR limit_millicents >= 0),
          -- A token scope needs a token limit; the cost scope needs a cost one.
          CHECK (scope = 'global_monthly' OR limit_tokens IS NOT NULL),
          CHECK (scope <> 'global_monthly' OR limit_millicents IS NOT NULL)
        );

        -- Every request that consumed or was refused budget. 'reserved' rows
        -- count against the limit while a call is in flight, so two concurrent
        -- requests cannot both fit under the same remaining headroom.
        CREATE TABLE ai_usage_entries (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id UUID NOT NULL REFERENCES users(id),
          conversation_id UUID NOT NULL,
          provider_code VARCHAR(64),
          model_code VARCHAR(128),
          prompt_tokens INTEGER NOT NULL DEFAULT 0,
          completion_tokens INTEGER NOT NULL DEFAULT 0,
          total_tokens INTEGER NOT NULL DEFAULT 0,
          cost_millicents BIGINT NOT NULL DEFAULT 0,
          state VARCHAR(16) NOT NULL DEFAULT 'reserved',
          refusal_code VARCHAR(64),
          limitation_label_code VARCHAR(64) NOT NULL,
          limitation_label_version VARCHAR(32) NOT NULL,
          idempotency_key VARCHAR(255) NOT NULL,
          occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (idempotency_key),
          CHECK (state IN ('reserved','committed','released','refused')),
          CHECK (prompt_tokens >= 0 AND completion_tokens >= 0 AND total_tokens >= 0),
          CHECK (cost_millicents >= 0),
          CHECK (state <> 'refused' OR refusal_code IS NOT NULL),
          CHECK (state <> 'committed' OR provider_code IS NOT NULL)
        );
        CREATE INDEX ai_usage_entries_user_day_idx
          ON ai_usage_entries (user_id, occurred_at) WHERE state IN ('reserved','committed');
        CREATE INDEX ai_usage_entries_conversation_idx
          ON ai_usage_entries (conversation_id) WHERE state IN ('reserved','committed');
        CREATE INDEX ai_usage_entries_month_idx
          ON ai_usage_entries (occurred_at) WHERE state IN ('reserved','committed');

        -- Ships EMPTY. Content-policy wording is a legal and clinical decision,
        -- not a developer's guess (DEC-003 discipline).
        CREATE TABLE ai_content_policy_rules (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          rule_code VARCHAR(64) NOT NULL,
          category VARCHAR(64) NOT NULL,
          match_kind VARCHAR(16) NOT NULL,
          pattern TEXT NOT NULL,
          action VARCHAR(16) NOT NULL,
          severity INTEGER NOT NULL DEFAULT 1,
          surface VARCHAR(8) NOT NULL DEFAULT 'input',
          locale VARCHAR(16),
          -- Optional pointer to the policy document in ai_safety_policies. No
          -- FK: this module deploys independently of the assistant module.
          safety_policy_code VARCHAR(128),
          is_active BOOLEAN NOT NULL DEFAULT true,
          updated_by UUID REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (rule_code),
          CHECK (match_kind IN ('keyword','exact')),
          CHECK (action IN ('allow','flag','block','escalate')),
          CHECK (surface IN ('input','output')),
          CHECK (severity BETWEEN 0 AND 10),
          CHECK (length(btrim(pattern)) > 0)
        );

        -- The screening audit. Rule codes and counts, never the member's text:
        -- an audit trail is not a second copy of the conversation.
        CREATE TABLE ai_policy_decisions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id UUID NOT NULL REFERENCES users(id),
          conversation_id UUID NOT NULL,
          message_id UUID,
          surface VARCHAR(8) NOT NULL,
          action VARCHAR(16) NOT NULL,
          matched_rule_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
          highest_severity INTEGER NOT NULL DEFAULT 0,
          audit JSONB NOT NULL DEFAULT '{}'::jsonb,
          decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (surface IN ('input','output')),
          CHECK (action IN ('allow','flag','block','escalate')),
          CHECK (jsonb_typeof(matched_rule_codes) = 'array')
        );
        CREATE INDEX ai_policy_decisions_recent_idx ON ai_policy_decisions (decided_at DESC);
        CREATE INDEX ai_policy_decisions_action_idx
          ON ai_policy_decisions (action, decided_at DESC) WHERE action <> 'allow';

        -- Ships EMPTY. The platform invents no crisis hotline numbers. The
        -- CHECK is the enforcement: an active resource must have been verified
        -- by a named person, and route_crisis ignores anything else.
        CREATE TABLE ai_crisis_resources (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          resource_code VARCHAR(64) NOT NULL,
          geography_code VARCHAR(8) NOT NULL,
          locale VARCHAR(16) NOT NULL,
          contact_kind VARCHAR(16) NOT NULL,
          contact_value TEXT NOT NULL,
          is_active BOOLEAN NOT NULL DEFAULT false,
          verified_by UUID REFERENCES users(id),
          verified_at TIMESTAMPTZ,
          verification_note TEXT,
          updated_by UUID REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (resource_code, geography_code, locale),
          CHECK (contact_kind IN ('phone','sms','url','email')),
          CHECK (is_active = false OR (verified_by IS NOT NULL AND verified_at IS NOT NULL))
        );
        CREATE INDEX ai_crisis_resources_lookup_idx
          ON ai_crisis_resources (geography_code, locale) WHERE is_active = true;

        -- Ships EMPTY. Without a row here the launch-readiness check reports
        -- human_escalation_runbook as unmet, which is the point.
        CREATE TABLE ai_escalation_runbooks (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          runbook_code VARCHAR(64) NOT NULL,
          geography_code VARCHAR(8),
          owner_role_code VARCHAR(64) NOT NULL,
          document_reference TEXT NOT NULL,
          acknowledgement_target_minutes INTEGER NOT NULL DEFAULT 30,
          is_active BOOLEAN NOT NULL DEFAULT false,
          approved_by UUID REFERENCES users(id),
          approved_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (runbook_code),
          CHECK (acknowledgement_target_minutes BETWEEN 1 AND 10080),
          CHECK (is_active = false OR (approved_by IS NOT NULL AND approved_at IS NOT NULL))
        );

        -- One row per referral to a human. The dedupe key means a member who
        -- sends five messages in a crisis gets one ticket, not five.
        CREATE TABLE ai_human_escalations (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id UUID NOT NULL REFERENCES users(id),
          conversation_id UUID NOT NULL,
          reason_code VARCHAR(128) NOT NULL,
          severity INTEGER NOT NULL DEFAULT 0,
          status VARCHAR(16) NOT NULL DEFAULT 'open',
          geography_code VARCHAR(8),
          runbook_id UUID REFERENCES ai_escalation_runbooks(id),
          handled_by UUID REFERENCES users(id),
          resolution_note TEXT,
          dedupe_key VARCHAR(255) NOT NULL,
          opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          acknowledged_at TIMESTAMPTZ,
          resolved_at TIMESTAMPTZ,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (dedupe_key),
          CHECK (status IN ('open','acknowledged','resolved','cancelled')),
          CHECK (severity BETWEEN 0 AND 10),
          CHECK (status <> 'acknowledged' OR acknowledged_at IS NOT NULL),
          CHECK (status NOT IN ('resolved','cancelled') OR resolved_at IS NOT NULL)
        );
        CREATE INDEX ai_human_escalations_queue_idx
          ON ai_human_escalations (severity DESC, opened_at) WHERE status IN ('open','acknowledged');

        -- Ships EMPTY, and no column defaults to true. An absent gate is unmet.
        CREATE TABLE ai_launch_gates (
          gate_code VARCHAR(64) PRIMARY KEY,
          is_met BOOLEAN NOT NULL DEFAULT false,
          evidence_ref TEXT,
          note TEXT,
          checked_by UUID REFERENCES users(id),
          checked_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (gate_code IN ('human_escalation_runbook','crisis_resources_configured','content_policy_configured','budget_limits_configured','provider_fallback_configured','limitation_label_configured')),
          -- A gate cannot be met without something to point at.
          CHECK (is_met = false OR (evidence_ref IS NOT NULL AND checked_at IS NOT NULL))
        );
        """
    )


def downgrade() -> None:
    _run(
        """
        DROP TABLE IF EXISTS ai_launch_gates;
        DROP TABLE IF EXISTS ai_human_escalations;
        DROP TABLE IF EXISTS ai_escalation_runbooks;
        DROP TABLE IF EXISTS ai_crisis_resources;
        DROP TABLE IF EXISTS ai_policy_decisions;
        DROP TABLE IF EXISTS ai_content_policy_rules;
        DROP TABLE IF EXISTS ai_usage_entries;
        DROP TABLE IF EXISTS ai_budget_policies;
        DROP TABLE IF EXISTS ai_provider_health;
        DROP TABLE IF EXISTS ai_provider_profiles;
        """
    )
