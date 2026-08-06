"""Create safety cases, evidence and human-review tasks.

Revision ID: 20260805_0078
Revises: 20260805_0077
"""

# ruff: noqa: E501

from alembic import op

revision = "20260805_0078"
down_revision = "20260805_0077"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run("""
    CREATE TABLE safety_cases (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), case_number VARCHAR(64) NOT NULL UNIQUE,
      case_type VARCHAR(64) NOT NULL, status VARCHAR(32) NOT NULL DEFAULT 'open',
      priority VARCHAR(32) NOT NULL, subject_user_id UUID REFERENCES users(id),
      risk_level VARCHAR(32) NOT NULL, primary_category VARCHAR(64) NOT NULL,
      source_manifest JSONB NOT NULL, rule_hit_manifest JSONB NOT NULL DEFAULT '[]'::jsonb,
      assigned_team VARCHAR(128), assigned_to UUID REFERENCES users(id), sla_due_at TIMESTAMPTZ,
      summary_encrypted TEXT, investigation_notes_encrypted TEXT, current_decision_id UUID,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), assigned_at TIMESTAMPTZ,
      resolved_at TIMESTAMPTZ, closed_at TIMESTAMPTZ, version INTEGER NOT NULL DEFAULT 1,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CHECK (status IN ('open','triaged','assigned','investigating','pending_action','resolved','closed','reopened')),
      CHECK (priority IN ('low','normal','high','urgent','critical')),
      CHECK (risk_level IN ('none','low','moderate','high','critical'))
    );
    CREATE TABLE safety_case_reports (
      safety_case_id UUID NOT NULL REFERENCES safety_cases(id), report_id UUID NOT NULL REFERENCES safety_reports(id),
      linked_at TIMESTAMPTZ NOT NULL DEFAULT now(), linked_by UUID REFERENCES users(id),
      PRIMARY KEY(safety_case_id,report_id)
    );
    CREATE TABLE safety_evidence_items (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), safety_case_id UUID NOT NULL REFERENCES safety_cases(id),
      evidence_type VARCHAR(64) NOT NULL, source_module VARCHAR(64) NOT NULL, source_reference_id UUID,
      evidence_snapshot_encrypted JSONB NOT NULL, evidence_checksum_sha256 VARCHAR(64) NOT NULL,
      collection_reason VARCHAR(128) NOT NULL, collected_by_type VARCHAR(32) NOT NULL,
      collected_by_user_id UUID REFERENCES users(id), sensitivity VARCHAR(32) NOT NULL,
      preservation_status VARCHAR(32) NOT NULL DEFAULT 'active', retention_policy_code VARCHAR(128),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), expires_at TIMESTAMPTZ,
      CHECK (sensitivity IN ('internal','sensitive','highly_restricted'))
    );
    CREATE TABLE safety_evidence_access_log (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), evidence_item_id UUID NOT NULL REFERENCES safety_evidence_items(id),
      actor_user_id UUID NOT NULL REFERENCES users(id), purpose_code VARCHAR(128) NOT NULL,
      access_type VARCHAR(32) NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE safety_case_tasks (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), safety_case_id UUID NOT NULL REFERENCES safety_cases(id),
      task_type VARCHAR(64) NOT NULL, status VARCHAR(32) NOT NULL DEFAULT 'open', assigned_to UUID REFERENCES users(id),
      due_at TIMESTAMPTZ, task_payload_encrypted JSONB NOT NULL DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), completed_at TIMESTAMPTZ
    );
    CREATE INDEX ix_safety_cases_queue ON safety_cases(status,priority,sla_due_at);
    CREATE INDEX ix_safety_evidence_case ON safety_evidence_items(safety_case_id,created_at);
    """)


def downgrade() -> None:
    _run("""
    DROP TABLE safety_case_tasks;
    DROP TABLE safety_evidence_access_log;
    DROP TABLE safety_evidence_items;
    DROP TABLE safety_case_reports;
    DROP TABLE safety_cases;
    """)
