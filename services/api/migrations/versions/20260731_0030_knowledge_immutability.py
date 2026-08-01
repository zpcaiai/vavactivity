"""Enforce immutable knowledge-version payloads and source-update versioning.

Revision ID: 20260731_0030
Revises: 20260731_0029
"""

from alembic import op

revision = "20260731_0030"
down_revision = "20260731_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "knowledge_document_versions_document_id_checksum_sha256_key",
        "knowledge_document_versions",
        type_="unique",
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_knowledge_version_payload_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.status IN ('review_required','approved','published','blocked','rejected')
             AND (
               NEW.checksum_sha256 IS DISTINCT FROM OLD.checksum_sha256 OR
               NEW.mime_type IS DISTINCT FROM OLD.mime_type OR
               NEW.raw_text_encrypted IS DISTINCT FROM OLD.raw_text_encrypted OR
               NEW.normalized_text IS DISTINCT FROM OLD.normalized_text OR
               NEW.parsed_blocks IS DISTINCT FROM OLD.parsed_blocks OR
               NEW.source_reference_snapshot IS DISTINCT FROM OLD.source_reference_snapshot OR
               NEW.processing_configuration IS DISTINCT FROM OLD.processing_configuration
             )
          THEN
            RAISE EXCEPTION 'published knowledge version payload is immutable';
          END IF;
          RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER knowledge_version_payload_immutable
        BEFORE UPDATE ON knowledge_document_versions
        FOR EACH ROW EXECUTE FUNCTION prevent_knowledge_version_payload_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS knowledge_version_payload_immutable ON knowledge_document_versions"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_knowledge_version_payload_mutation")
    op.create_unique_constraint(
        "knowledge_document_versions_document_id_checksum_sha256_key",
        "knowledge_document_versions",
        ["document_id", "checksum_sha256"],
    )
