"""Require canonical external identifier hashes to be SHA-256 hex digests.

Revision ID: 20260808_0094
Revises: 20260806_0093
"""

from alembic import op

revision = "20260808_0094"
down_revision = "20260806_0093"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE canonical_external_identifiers
        DROP CONSTRAINT IF EXISTS canonical_external_identifiers_external_identifier_hash_check
        """
    )
    op.execute(
        """
        ALTER TABLE canonical_external_identifiers
        ADD CONSTRAINT ck_canonical_external_identifier_sha256
        CHECK (external_identifier_hash ~ '^[0-9a-f]{64}$')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE canonical_external_identifiers
        DROP CONSTRAINT IF EXISTS ck_canonical_external_identifier_sha256
        """
    )
    op.execute(
        """
        ALTER TABLE canonical_external_identifiers
        ADD CONSTRAINT canonical_external_identifiers_external_identifier_hash_check
        CHECK (external_identifier_hash !~* '@|\\+?[0-9]{7,}')
        """
    )
