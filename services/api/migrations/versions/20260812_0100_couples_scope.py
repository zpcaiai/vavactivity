# ruff: noqa: E501

"""Two-sided couple binding and the SCOPE relationship assessment.

Covers COUPLE-001 and SCOPE-001.

Two structures carry the load here:

* ``couple_active_members`` — a primary key on ``user_id`` is what makes
  "one active binding per member" true under concurrency. An application check
  alone would lose a race between two simultaneous acceptances.
* ``couple_scope_free_benefits`` — keyed on ``pair_key`` (sorted user ids), not
  on ``couple_relationships.id``. Unbinding and rebinding the same two people
  creates a new relationship row but finds the same consumed benefit row, which
  is the entire point of SCOPE-001's "one free assessment per relationship".

No questionnaire content is inserted. ``scope_assessment_questions`` ships empty
and is authored by administrators (DEC-001).

Revision ID: 20260812_0100
Revises: 20260812_0099
"""

import re

from alembic import op

revision = "20260812_0100"
down_revision = "20260812_0099"
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
        -- One row per invitation. Sending one binds nobody: the relationship is
        -- only created when the *invitee* accepts (COUPLE-001).
        CREATE TABLE couple_invitations (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          pair_key VARCHAR(96) NOT NULL,
          inviter_user_id UUID NOT NULL REFERENCES users(id),
          invitee_user_id UUID NOT NULL REFERENCES users(id),
          relationship_kind VARCHAR(16) NOT NULL DEFAULT 'dating',
          status VARCHAR(16) NOT NULL DEFAULT 'pending',
          note_encrypted TEXT,
          expires_at TIMESTAMPTZ NOT NULL,
          responded_at TIMESTAMPTZ,
          decline_reason_code VARCHAR(64),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (inviter_user_id <> invitee_user_id),
          CHECK (relationship_kind IN ('dating','engaged','married')),
          CHECK (status IN ('pending','accepted','rejected','cancelled','expired')),
          CHECK (status = 'pending' OR responded_at IS NOT NULL OR status = 'expired')
        );
        -- At most one live invitation per pair, in either direction, so the two
        -- of them cannot each hold an invitation to the other.
        CREATE UNIQUE INDEX couple_invitations_pending_pair_idx
          ON couple_invitations (pair_key) WHERE status = 'pending';
        CREATE INDEX couple_invitations_invitee_idx
          ON couple_invitations (invitee_user_id, status, created_at DESC);
        CREATE INDEX couple_invitations_inviter_idx
          ON couple_invitations (inviter_user_id, status, created_at DESC);

        -- The binding. Rows are never deleted: an unbound relationship stays
        -- queryable so the free-benefit ledger can always be explained.
        CREATE TABLE couple_relationships (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          pair_key VARCHAR(96) NOT NULL,
          user_low_id UUID NOT NULL REFERENCES users(id),
          user_high_id UUID NOT NULL REFERENCES users(id),
          relationship_kind VARCHAR(16) NOT NULL,
          state VARCHAR(16) NOT NULL DEFAULT 'active',
          invitation_id UUID REFERENCES couple_invitations(id),
          bound_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          unbound_at TIMESTAMPTZ,
          unbound_by UUID REFERENCES users(id),
          unbind_reason TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (user_low_id <> user_high_id),
          CHECK (state IN ('active','unbound')),
          CHECK (relationship_kind IN ('dating','engaged','married')),
          CHECK (state <> 'unbound' OR unbound_at IS NOT NULL),
          -- A binding always originates from an accepted invitation. There is
          -- no unilateral path, and this constraint says so in the schema.
          CHECK (invitation_id IS NOT NULL)
        );
        CREATE INDEX couple_relationships_pair_idx ON couple_relationships (pair_key, created_at DESC);
        CREATE INDEX couple_relationships_state_idx ON couple_relationships (state);

        -- The uniqueness guarantee. A member holds at most one seat, so two
        -- concurrent acceptances cannot both win.
        CREATE TABLE couple_active_members (
          user_id UUID PRIMARY KEY REFERENCES users(id),
          relationship_id UUID NOT NULL REFERENCES couple_relationships(id),
          pair_key VARCHAR(96) NOT NULL,
          bound_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX couple_active_members_relationship_idx
          ON couple_active_members (relationship_id);

        -- Append-only. Every invite, answer, bind and unbind writes one row.
        CREATE TABLE couple_binding_events (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          pair_key VARCHAR(96) NOT NULL,
          event_type VARCHAR(24) NOT NULL,
          relationship_id UUID,
          invitation_id UUID,
          actor_id UUID REFERENCES users(id),
          actor_kind VARCHAR(16) NOT NULL,
          from_state VARCHAR(24),
          to_state VARCHAR(24),
          reason TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (actor_kind IN ('member','admin','system')),
          CHECK (event_type IN ('invited','accepted','rejected','cancelled','expired','bound','unbound','admin_unbound'))
        );
        CREATE INDEX couple_binding_events_pair_idx ON couple_binding_events (pair_key, created_at);
        CREATE INDEX couple_binding_events_relationship_idx
          ON couple_binding_events (relationship_id, created_at);

        -- SCOPE-001: exactly one free assessment per *pair*, forever.
        -- The primary key is pair_key, so an unbind/rebind cycle cannot mint a
        -- second free assessment. Deleting a row here would hand a pair a fresh
        -- benefit, which is why nothing in the codebase deletes from it.
        CREATE TABLE couple_scope_free_benefits (
          pair_key VARCHAR(96) PRIMARY KEY,
          user_low_id UUID NOT NULL REFERENCES users(id),
          user_high_id UUID NOT NULL REFERENCES users(id),
          granted INTEGER NOT NULL DEFAULT 1,
          consumed INTEGER NOT NULL DEFAULT 0,
          consumed_at TIMESTAMPTZ,
          consumed_relationship_id UUID REFERENCES couple_relationships(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (granted >= 0),
          CHECK (consumed >= 0),
          CHECK (consumed <= granted),
          CHECK (user_low_id <> user_high_id)
        );

        -- Versioned assessment definition. Immutable once published: editing a
        -- published version would change the meaning of historical reports.
        CREATE TABLE scope_assessment_versions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          version_code VARCHAR(128) NOT NULL,
          semantic_version VARCHAR(32) NOT NULL,
          algorithm_version VARCHAR(64) NOT NULL,
          status VARCHAR(16) NOT NULL DEFAULT 'draft',
          created_by UUID REFERENCES users(id),
          published_by UUID REFERENCES users(id),
          published_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (version_code, semantic_version),
          CHECK (status IN ('draft','published','archived')),
          CHECK (status <> 'published' OR (published_by IS NOT NULL AND published_at IS NOT NULL))
        );

        -- Ships EMPTY. No copyrighted questionnaire content is inserted by this
        -- migration or any other. Administrators author the bank (DEC-001).
        CREATE TABLE scope_assessment_questions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          version_id UUID NOT NULL REFERENCES scope_assessment_versions(id),
          question_code VARCHAR(64) NOT NULL,
          dimension VARCHAR(32) NOT NULL,
          prompt_text TEXT NOT NULL,
          weight INTEGER NOT NULL DEFAULT 1,
          scale_min INTEGER NOT NULL DEFAULT 1,
          scale_max INTEGER NOT NULL DEFAULT 5,
          reverse_scored BOOLEAN NOT NULL DEFAULT false,
          position INTEGER NOT NULL DEFAULT 0,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (version_id, question_code),
          CHECK (dimension IN ('support','communication','outlook','partnership','expectations')),
          CHECK (weight BETWEEN 1 AND 10),
          CHECK (scale_min >= 1 AND scale_max <= 10 AND scale_min < scale_max)
        );
        CREATE INDEX scope_assessment_questions_version_idx
          ON scope_assessment_questions (version_id, position);

        CREATE TABLE scope_assessments (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          relationship_id UUID NOT NULL REFERENCES couple_relationships(id),
          pair_key VARCHAR(96) NOT NULL,
          version_id UUID NOT NULL REFERENCES scope_assessment_versions(id),
          state VARCHAR(16) NOT NULL DEFAULT 'collecting',
          entitlement_source VARCHAR(16) NOT NULL DEFAULT 'free',
          free_benefit_key VARCHAR(160),
          completed_at TIMESTAMPTZ,
          cancelled_at TIMESTAMPTZ,
          cancel_reason VARCHAR(64),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (relationship_id, version_id),
          CHECK (state IN ('collecting','completed','report_ready','cancelled')),
          CHECK (entitlement_source IN ('free','paid','admin_grant')),
          CHECK (entitlement_source <> 'free' OR free_benefit_key IS NOT NULL)
        );
        CREATE INDEX scope_assessments_pair_idx ON scope_assessments (pair_key, created_at DESC);

        -- SEALED. answers_encrypted is opaque at rest and is decrypted only for
        -- its author or inside scoring, which emits numbers (SCOPE-001).
        CREATE TABLE scope_participant_submissions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          assessment_id UUID NOT NULL REFERENCES scope_assessments(id),
          user_id UUID NOT NULL REFERENCES users(id),
          status VARCHAR(16) NOT NULL DEFAULT 'not_started',
          answers_encrypted TEXT,
          answer_count INTEGER NOT NULL DEFAULT 0,
          submitted_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (assessment_id, user_id),
          CHECK (status IN ('not_started','in_progress','submitted')),
          -- A submitted row must actually carry answers and a timestamp. This is
          -- the database half of the completion barrier.
          CHECK (status <> 'submitted' OR (answers_encrypted IS NOT NULL AND submitted_at IS NOT NULL))
        );

        -- Deterministic scores. Not encrypted: these are the numbers that must
        -- stay queryable and re-derivable from (answers, version, algorithm).
        CREATE TABLE scope_dimension_scores (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          assessment_id UUID NOT NULL REFERENCES scope_assessments(id),
          user_id UUID NOT NULL REFERENCES users(id),
          dimension VARCHAR(32) NOT NULL,
          raw_total INTEGER NOT NULL,
          min_total INTEGER NOT NULL,
          max_total INTEGER NOT NULL,
          normalized_score NUMERIC(6,2) NOT NULL,
          algorithm_version VARCHAR(64) NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (assessment_id, user_id, dimension),
          CHECK (dimension IN ('support','communication','outlook','partnership','expectations')),
          CHECK (normalized_score >= 0 AND normalized_score <= 100),
          CHECK (max_total > min_total)
        );

        -- scores (deterministic) and advice_* (AI narrative) are separate
        -- columns on purpose: nobody should be able to mistake generated prose
        -- for a computed score, and dropping the advice must not touch scores.
        CREATE TABLE scope_reports (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          assessment_id UUID NOT NULL REFERENCES scope_assessments(id),
          version_id UUID NOT NULL REFERENCES scope_assessment_versions(id),
          algorithm_version VARCHAR(64) NOT NULL,
          scores JSONB NOT NULL,
          scores_fingerprint VARCHAR(64) NOT NULL,
          idempotency_key VARCHAR(255) NOT NULL,
          advice_status VARCHAR(16) NOT NULL DEFAULT 'absent',
          advice_encrypted TEXT,
          advice_model VARCHAR(64),
          advice_prompt_version VARCHAR(64),
          advice_generated_at TIMESTAMPTZ,
          advice_disclaimer_code VARCHAR(128),
          generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (assessment_id),
          UNIQUE (idempotency_key),
          CHECK (advice_status IN ('absent','generated','failed')),
          CHECK (advice_status <> 'generated' OR (advice_encrypted IS NOT NULL AND advice_model IS NOT NULL))
        );
        """
    )


def downgrade() -> None:
    _run(
        """
        DROP TABLE IF EXISTS scope_reports;
        DROP TABLE IF EXISTS scope_dimension_scores;
        DROP TABLE IF EXISTS scope_participant_submissions;
        DROP TABLE IF EXISTS scope_assessments;
        DROP TABLE IF EXISTS scope_assessment_questions;
        DROP TABLE IF EXISTS scope_assessment_versions;
        DROP TABLE IF EXISTS couple_scope_free_benefits;
        DROP TABLE IF EXISTS couple_binding_events;
        DROP TABLE IF EXISTS couple_active_members;
        DROP TABLE IF EXISTS couple_relationships;
        DROP TABLE IF EXISTS couple_invitations;
        """
    )
