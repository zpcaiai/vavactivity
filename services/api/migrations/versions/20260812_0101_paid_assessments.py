# ruff: noqa: E501

"""Generic paid assessment catalogue, purchase, entitlement and report schema.

Covers ASSESS-001.

Three things this schema enforces that application code alone could not:

* ``assessment_versions`` carries a CHECK that a ``published`` row must have a
  ``license_reference``, a ``license_verified_at`` and a ``license_verified_by``.
  Publishing unlicensed content is therefore impossible even by direct SQL.
* ``assessment_entitlements.version_id`` is NOT NULL and every attempt and
  report carries the same column, so "the member's version" is always a stored
  value and never a lookup of the product's newest version.
* ``assessment_refund_events`` is append-only and records refusals as well as
  refunds, so a refund decision is always explainable afterwards.

No DISC, MBTI, Five Love Languages or any other licensed instrument's items are
inserted. ``assessment_version_questions`` ships empty.

Revision ID: 20260812_0101
Revises: 20260812_0100
"""

from alembic import op

revision = "20260812_0101"
down_revision = "20260812_0100"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(
        """
        CREATE TABLE assessment_products (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          product_code VARCHAR(128) NOT NULL,
          -- An identifier the frontend localizes, not display copy. The backend
          -- ships no user-facing wording.
          title_code VARCHAR(128) NOT NULL,
          category_code VARCHAR(64) NOT NULL,
          status VARCHAR(16) NOT NULL DEFAULT 'draft',
          refund_window_hours INTEGER NOT NULL DEFAULT 72,
          created_by UUID REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (product_code),
          CHECK (status IN ('draft','active','retired')),
          CHECK (refund_window_hours >= 0)
        );

        -- The licensing gate. A published version must name where its content
        -- came from, cite a reference, and record who verified it (ASSESS-001).
        CREATE TABLE assessment_versions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          product_id UUID NOT NULL REFERENCES assessment_products(id),
          semantic_version VARCHAR(32) NOT NULL,
          algorithm_version VARCHAR(64) NOT NULL,
          status VARCHAR(16) NOT NULL DEFAULT 'draft',
          content_source VARCHAR(32) NOT NULL,
          license_reference VARCHAR(255),
          license_verified_at TIMESTAMPTZ,
          license_verified_by UUID REFERENCES users(id),
          licensor_name VARCHAR(255),
          license_note TEXT,
          question_count INTEGER NOT NULL DEFAULT 0,
          price_minor_units INTEGER NOT NULL DEFAULT 0,
          currency VARCHAR(3) NOT NULL DEFAULT 'CNY',
          published_by UUID REFERENCES users(id),
          published_at TIMESTAMPTZ,
          retired_at TIMESTAMPTZ,
          created_by UUID REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (product_id, semantic_version),
          CHECK (status IN ('draft','published','retired')),
          CHECK (content_source IN ('administrator_authored','licensed_third_party','public_domain','partner_supplied')),
          CHECK (price_minor_units >= 0),
          -- The rule, in the schema: no licence reference, no publication.
          CHECK (
            status <> 'published'
            OR (
              license_reference IS NOT NULL
              AND length(btrim(license_reference)) >= 3
              AND license_verified_at IS NOT NULL
              AND license_verified_by IS NOT NULL
              AND published_at IS NOT NULL
              AND price_minor_units > 0
              AND question_count > 0
            )
          ),
          -- Third-party and partner content must additionally name the licensor.
          CHECK (
            status <> 'published'
            OR content_source NOT IN ('licensed_third_party','partner_supplied')
            OR (licensor_name IS NOT NULL AND length(btrim(licensor_name)) > 0)
          )
        );
        CREATE INDEX assessment_versions_product_idx ON assessment_versions (product_id, status);

        -- Ships EMPTY. Licensed instruments are authored against a version whose
        -- licence is recorded above. None of their items live in this repo.
        CREATE TABLE assessment_version_questions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          version_id UUID NOT NULL REFERENCES assessment_versions(id),
          question_code VARCHAR(64) NOT NULL,
          dimension_code VARCHAR(64) NOT NULL,
          prompt_text TEXT NOT NULL,
          weight INTEGER NOT NULL DEFAULT 1,
          scale_min INTEGER NOT NULL DEFAULT 1,
          scale_max INTEGER NOT NULL DEFAULT 5,
          reverse_scored BOOLEAN NOT NULL DEFAULT false,
          position INTEGER NOT NULL DEFAULT 0,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (version_id, question_code),
          CHECK (weight BETWEEN 1 AND 10),
          CHECK (scale_min >= 1 AND scale_max <= 10 AND scale_min < scale_max)
        );
        CREATE INDEX assessment_version_questions_version_idx
          ON assessment_version_questions (version_id, position);

        -- version_id is the anchor against post-purchase version drift.
        CREATE TABLE assessment_purchases (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id UUID NOT NULL REFERENCES users(id),
          product_id UUID NOT NULL REFERENCES assessment_products(id),
          version_id UUID NOT NULL REFERENCES assessment_versions(id),
          order_id VARCHAR(128) NOT NULL,
          status VARCHAR(16) NOT NULL DEFAULT 'pending',
          price_minor_units INTEGER NOT NULL,
          currency VARCHAR(3) NOT NULL DEFAULT 'CNY',
          idempotency_key VARCHAR(255) NOT NULL,
          purchased_at TIMESTAMPTZ,
          refunded_at TIMESTAMPTZ,
          refund_reason TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (idempotency_key),
          CHECK (status IN ('pending','paid','failed','cancelled','refunded')),
          CHECK (price_minor_units >= 0),
          CHECK (status <> 'refunded' OR refunded_at IS NOT NULL)
        );
        CREATE INDEX assessment_purchases_user_idx ON assessment_purchases (user_id, created_at DESC);

        CREATE TABLE assessment_entitlements (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id UUID NOT NULL REFERENCES users(id),
          purchase_id UUID NOT NULL REFERENCES assessment_purchases(id),
          product_id UUID NOT NULL REFERENCES assessment_products(id),
          -- NOT NULL by design: an entitlement without a pinned version would
          -- have to fall back to "latest", which is the bug this prevents.
          version_id UUID NOT NULL REFERENCES assessment_versions(id),
          status VARCHAR(16) NOT NULL DEFAULT 'active',
          attempts_granted INTEGER NOT NULL DEFAULT 1,
          attempts_consumed INTEGER NOT NULL DEFAULT 0,
          expires_at TIMESTAMPTZ,
          revoked_at TIMESTAMPTZ,
          revoke_reason VARCHAR(64),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (purchase_id),
          CHECK (status IN ('active','consumed','revoked','expired')),
          CHECK (attempts_granted >= 1),
          CHECK (attempts_consumed >= 0),
          CHECK (attempts_consumed <= attempts_granted),
          CHECK (status <> 'revoked' OR revoked_at IS NOT NULL)
        );
        CREATE INDEX assessment_entitlements_user_idx ON assessment_entitlements (user_id, status);

        -- A voided attempt keeps its answers: they are the member's own data and
        -- may be needed to settle a dispute (ASSESS-001 refund policy).
        CREATE TABLE assessment_attempts (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          entitlement_id UUID NOT NULL REFERENCES assessment_entitlements(id),
          user_id UUID NOT NULL REFERENCES users(id),
          version_id UUID NOT NULL REFERENCES assessment_versions(id),
          status VARCHAR(16) NOT NULL DEFAULT 'in_progress',
          idempotency_key VARCHAR(255) NOT NULL,
          answers_encrypted TEXT,
          answer_count INTEGER NOT NULL DEFAULT 0,
          started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          submitted_at TIMESTAMPTZ,
          voided_at TIMESTAMPTZ,
          void_reason VARCHAR(64),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (idempotency_key),
          CHECK (status IN ('in_progress','submitted','scored','abandoned','voided')),
          CHECK (status NOT IN ('submitted','scored') OR submitted_at IS NOT NULL),
          CHECK (status <> 'voided' OR voided_at IS NOT NULL)
        );
        CREATE INDEX assessment_attempts_entitlement_idx
          ON assessment_attempts (entitlement_id, created_at DESC);

        -- A revoked report is retained, never deleted: it is the evidence of
        -- what the member was actually shown.
        CREATE TABLE assessment_reports (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          attempt_id UUID NOT NULL REFERENCES assessment_attempts(id),
          version_id UUID NOT NULL REFERENCES assessment_versions(id),
          algorithm_version VARCHAR(64) NOT NULL,
          scores JSONB NOT NULL,
          scores_fingerprint VARCHAR(64) NOT NULL,
          idempotency_key VARCHAR(255) NOT NULL,
          status VARCHAR(16) NOT NULL DEFAULT 'generated',
          advice_encrypted TEXT,
          advice_model VARCHAR(64),
          advice_prompt_version VARCHAR(64),
          advice_generated_at TIMESTAMPTZ,
          advice_disclaimer_code VARCHAR(128),
          revoked_at TIMESTAMPTZ,
          revoke_reason VARCHAR(64),
          generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (attempt_id),
          UNIQUE (idempotency_key),
          CHECK (status IN ('generated','revoked')),
          CHECK (status <> 'revoked' OR revoked_at IS NOT NULL)
        );

        -- Append-only, and it records refusals too, so "why was I not refunded"
        -- always has a stored answer.
        CREATE TABLE assessment_refund_events (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          purchase_id UUID NOT NULL REFERENCES assessment_purchases(id),
          entitlement_id UUID REFERENCES assessment_entitlements(id),
          trigger VARCHAR(32) NOT NULL,
          attempt_action VARCHAR(24) NOT NULL,
          report_action VARCHAR(24) NOT NULL,
          refund_allowed BOOLEAN NOT NULL,
          reason_code VARCHAR(64) NOT NULL,
          reason TEXT,
          actor_id UUID REFERENCES users(id),
          actor_kind VARCHAR(16) NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (trigger IN ('member_request','payment_reversal','admin_goodwill','license_withdrawn')),
          CHECK (attempt_action IN ('none','void','retain_sealed')),
          CHECK (report_action IN ('none','revoke_access')),
          CHECK (actor_kind IN ('member','admin','system'))
        );
        CREATE INDEX assessment_refund_events_purchase_idx
          ON assessment_refund_events (purchase_id, created_at DESC);
        """
    )


def downgrade() -> None:
    _run(
        """
        DROP TABLE IF EXISTS assessment_refund_events;
        DROP TABLE IF EXISTS assessment_reports;
        DROP TABLE IF EXISTS assessment_attempts;
        DROP TABLE IF EXISTS assessment_entitlements;
        DROP TABLE IF EXISTS assessment_purchases;
        DROP TABLE IF EXISTS assessment_version_questions;
        DROP TABLE IF EXISTS assessment_versions;
        DROP TABLE IF EXISTS assessment_products;
        """
    )
