"""Complete governed knowledge ingestion, parsing and index metadata.

Revision ID: 20260731_0029
Revises: 20260731_0028
"""

# ruff: noqa: E501

from alembic import op

revision = "20260731_0029"
down_revision = "20260731_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = """
    ALTER TABLE knowledge_spaces ADD COLUMN supported_locales jsonb NOT NULL DEFAULT '["zh-CN","zh-TW","en"]';
    ALTER TABLE knowledge_spaces ADD COLUMN default_sensitivity varchar(32) NOT NULL DEFAULT 'internal';
    ALTER TABLE knowledge_spaces ADD COLUMN retrieval_policy jsonb NOT NULL DEFAULT '{}';
    ALTER TABLE knowledge_spaces ADD COLUMN updated_by uuid REFERENCES users(id);

    ALTER TABLE knowledge_sources ADD COLUMN source_reference_type varchar(64);
    ALTER TABLE knowledge_sources ADD COLUMN source_reference_id uuid;
    ALTER TABLE knowledge_sources ADD COLUMN sync_mode varchar(32) NOT NULL DEFAULT 'manual';
    ALTER TABLE knowledge_sources ADD COLUMN last_synced_at timestamptz;
    ALTER TABLE knowledge_sources ADD COLUMN next_sync_at timestamptz;
    ALTER TABLE knowledge_sources ADD COLUMN last_sync_version varchar(128);
    ALTER TABLE knowledge_sources ADD COLUMN created_by uuid REFERENCES users(id);
    ALTER TABLE knowledge_sources ADD COLUMN version integer NOT NULL DEFAULT 1;
    ALTER TABLE knowledge_sources ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();

    ALTER TABLE knowledge_authorizations ADD COLUMN rights_holder_name varchar(300) NOT NULL DEFAULT 'VAV';
    ALTER TABLE knowledge_authorizations ADD COLUMN document_id uuid REFERENCES knowledge_documents(id);
    ALTER TABLE knowledge_authorizations ADD COLUMN authorization_basis varchar(64) NOT NULL DEFAULT 'owned_by_vav';
    ALTER TABLE knowledge_authorizations ADD COLUMN allowed_uses jsonb NOT NULL DEFAULT '["rag_retrieval"]';
    ALTER TABLE knowledge_authorizations ADD COLUMN prohibited_uses jsonb NOT NULL DEFAULT '["external_model_training"]';
    ALTER TABLE knowledge_authorizations ADD COLUMN prohibited_regions jsonb NOT NULL DEFAULT '[]';
    ALTER TABLE knowledge_authorizations ADD COLUMN citation_permission varchar(64) NOT NULL DEFAULT 'none';
    ALTER TABLE knowledge_authorizations ADD COLUMN evidence_reference text;
    ALTER TABLE knowledge_authorizations ADD COLUMN approved_at timestamptz;
    ALTER TABLE knowledge_authorizations ADD COLUMN revoked_by uuid REFERENCES users(id);
    ALTER TABLE knowledge_authorizations ADD COLUMN revocation_reason text;
    ALTER TABLE knowledge_authorizations ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();

    ALTER TABLE knowledge_documents ADD COLUMN space_id uuid REFERENCES knowledge_spaces(id);
    UPDATE knowledge_documents d SET space_id=s.space_id FROM knowledge_sources s WHERE s.id=d.source_id;
    ALTER TABLE knowledge_documents ALTER COLUMN space_id SET NOT NULL;
    ALTER TABLE knowledge_documents ADD COLUMN document_type varchar(64) NOT NULL DEFAULT 'manual_entry';
    ALTER TABLE knowledge_documents ADD COLUMN sensitivity varchar(32) NOT NULL DEFAULT 'internal';
    ALTER TABLE knowledge_documents ADD COLUMN published_version_id uuid REFERENCES knowledge_document_versions(id);
    ALTER TABLE knowledge_documents ADD COLUMN owner_name varchar(300);
    ALTER TABLE knowledge_documents ADD COLUMN original_publication_date date;
    ALTER TABLE knowledge_documents ADD COLUMN valid_from timestamptz;
    ALTER TABLE knowledge_documents ADD COLUMN valid_until timestamptz;
    ALTER TABLE knowledge_documents ADD COLUMN created_by uuid REFERENCES users(id);
    ALTER TABLE knowledge_documents ADD COLUMN updated_by uuid REFERENCES users(id);
    ALTER TABLE knowledge_documents ADD COLUMN version integer NOT NULL DEFAULT 1;
    ALTER TABLE knowledge_documents ADD COLUMN archived_at timestamptz;

    ALTER TABLE knowledge_document_versions ADD COLUMN version_label varchar(128);
    ALTER TABLE knowledge_document_versions ADD COLUMN source_media_id uuid REFERENCES media_assets(id);
    ALTER TABLE knowledge_document_versions ADD COLUMN source_filename varchar(500);
    ALTER TABLE knowledge_document_versions ADD COLUMN source_byte_size bigint;
    ALTER TABLE knowledge_document_versions ADD COLUMN source_reference_snapshot jsonb NOT NULL DEFAULT '{}';
    ALTER TABLE knowledge_document_versions ADD COLUMN processing_configuration jsonb NOT NULL DEFAULT '{}';
    ALTER TABLE knowledge_document_versions ADD COLUMN created_by uuid REFERENCES users(id);

    CREATE TABLE knowledge_uploads (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), source_id uuid NOT NULL REFERENCES knowledge_sources(id),
      document_code varchar(128) NOT NULL, title varchar(500) NOT NULL, locale varchar(16) NOT NULL,
      filename varchar(500) NOT NULL, declared_mime_type varchar(128) NOT NULL,
      expected_byte_size bigint NOT NULL, expected_sha256 varchar(64) NOT NULL,
      bucket_name varchar(128) NOT NULL, object_key_encrypted text NOT NULL,
      status varchar(32) NOT NULL DEFAULT 'pending_upload', virus_scan_status varchar(32) NOT NULL DEFAULT 'not_run',
      created_by uuid NOT NULL REFERENCES users(id), expires_at timestamptz NOT NULL,
      completed_at timestamptz, created_at timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE knowledge_parsed_blocks (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), document_version_id uuid NOT NULL REFERENCES knowledge_document_versions(id),
      block_index integer NOT NULL, block_id varchar(128) NOT NULL, block_type varchar(32) NOT NULL,
      raw_text_encrypted text, normalized_text text, heading_level integer, page_number integer,
      section_path jsonb NOT NULL DEFAULT '[]', source_locator jsonb NOT NULL DEFAULT '{}',
      parsing_metadata jsonb NOT NULL DEFAULT '{}', parent_block_id varchar(128), created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(document_version_id, block_index), UNIQUE(document_version_id, block_id)
    );
    CREATE TABLE knowledge_parsing_reports (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), document_version_id uuid NOT NULL UNIQUE REFERENCES knowledge_document_versions(id),
      parser_name varchar(128) NOT NULL, parser_version varchar(64) NOT NULL,
      text_character_count integer NOT NULL, block_count integer NOT NULL, page_count integer,
      quality_score_basis_points integer NOT NULL, warnings jsonb NOT NULL DEFAULT '[]', errors jsonb NOT NULL DEFAULT '[]',
      requires_manual_review boolean NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
    );

    ALTER TABLE knowledge_processing_jobs ADD COLUMN current_stage varchar(64);
    ALTER TABLE knowledge_processing_jobs ADD COLUMN progress_basis_points integer NOT NULL DEFAULT 0;
    ALTER TABLE knowledge_processing_jobs ADD COLUMN configuration_snapshot jsonb NOT NULL DEFAULT '{}';
    ALTER TABLE knowledge_processing_jobs ADD COLUMN next_attempt_at timestamptz;
    ALTER TABLE knowledge_processing_jobs ADD COLUMN error_message_safe text;
    ALTER TABLE knowledge_processing_jobs ADD COLUMN started_at timestamptz;
    ALTER TABLE knowledge_processing_jobs ADD COLUMN completed_at timestamptz;

    ALTER TABLE knowledge_findings ADD COLUMN finding_value_hash varchar(128);
    ALTER TABLE knowledge_findings ADD COLUMN reviewed_by uuid REFERENCES users(id);
    ALTER TABLE knowledge_findings ADD COLUMN reviewed_at timestamptz;
    ALTER TABLE knowledge_findings ADD COLUMN resolution text;

    ALTER TABLE knowledge_embedding_profiles ADD COLUMN model_revision varchar(128);
    ALTER TABLE knowledge_embedding_profiles ADD COLUMN multilingual boolean NOT NULL DEFAULT true;
    ALTER TABLE knowledge_embedding_profiles ADD COLUMN configuration jsonb NOT NULL DEFAULT '{}';
    ALTER TABLE knowledge_embeddings ADD COLUMN provider_request_id varchar(255);
    ALTER TABLE knowledge_embeddings ADD COLUMN status varchar(32) NOT NULL DEFAULT 'succeeded';
    ALTER TABLE knowledge_embeddings ADD COLUMN attempts integer NOT NULL DEFAULT 1;
    ALTER TABLE knowledge_embeddings ADD COLUMN cost_microunits bigint NOT NULL DEFAULT 0;
    ALTER TABLE knowledge_embeddings ADD COLUMN error_code varchar(128);

    ALTER TABLE knowledge_index_versions ADD COLUMN retrieval_configuration jsonb NOT NULL DEFAULT '{}';
    ALTER TABLE knowledge_index_versions ADD COLUMN document_version_manifest jsonb NOT NULL DEFAULT '[]';
    ALTER TABLE knowledge_index_versions ADD COLUMN chunk_count integer NOT NULL DEFAULT 0;
    ALTER TABLE knowledge_index_versions ADD COLUMN embedding_count integer NOT NULL DEFAULT 0;
    ALTER TABLE knowledge_index_versions ADD COLUMN validation_report jsonb;
    ALTER TABLE knowledge_index_versions ADD COLUMN created_by uuid REFERENCES users(id);
    ALTER TABLE knowledge_index_versions ADD COLUMN activated_by uuid REFERENCES users(id);

    ALTER TABLE knowledge_chunks ADD COLUMN block_ids jsonb NOT NULL DEFAULT '[]';
    ALTER TABLE knowledge_chunks ADD COLUMN page_start integer;
    ALTER TABLE knowledge_chunks ADD COLUMN page_end integer;
    ALTER TABLE knowledge_chunks ADD COLUMN previous_chunk_id uuid REFERENCES knowledge_chunks(id);
    ALTER TABLE knowledge_chunks ADD COLUMN next_chunk_id uuid REFERENCES knowledge_chunks(id);
    CREATE INDEX knowledge_chunks_roles_gin ON knowledge_chunks USING gin(allowed_roles);

    ALTER TABLE knowledge_retrieval_queries ADD COLUMN query_sha256 varchar(64);
    ALTER TABLE knowledge_retrieval_queries ADD COLUMN purpose varchar(64) NOT NULL DEFAULT 'rag_retrieval';
    ALTER TABLE knowledge_retrieval_queries ADD COLUMN region varchar(32);
    ALTER TABLE knowledge_retrieval_queries ADD COLUMN candidate_count integer NOT NULL DEFAULT 0;
    ALTER TABLE knowledge_retrieval_queries ADD COLUMN index_version_id uuid REFERENCES knowledge_index_versions(id);
    ALTER TABLE knowledge_citations ADD COLUMN title_path jsonb NOT NULL DEFAULT '[]';
    ALTER TABLE knowledge_citations ADD COLUMN citation_permission varchar(64) NOT NULL DEFAULT 'none';

    ALTER TABLE knowledge_evaluation_datasets ADD COLUMN version integer NOT NULL DEFAULT 1;
    ALTER TABLE knowledge_evaluation_cases ADD COLUMN region varchar(32);
    ALTER TABLE knowledge_evaluation_cases ADD COLUMN required_concepts jsonb NOT NULL DEFAULT '[]';
    ALTER TABLE knowledge_evaluation_cases ADD COLUMN safety_boundary boolean NOT NULL DEFAULT false;

    CREATE TABLE knowledge_audit_events (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), event_type varchar(128) NOT NULL,
      actor_id uuid REFERENCES users(id), subject_type varchar(64) NOT NULL, subject_id uuid NOT NULL,
      reason text, details_encrypted text, created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX knowledge_audit_subject ON knowledge_audit_events(subject_type, subject_id, created_at);
    """
    for statement in statements.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_audit_events")
    op.execute("DROP TABLE IF EXISTS knowledge_parsing_reports")
    op.execute("DROP TABLE IF EXISTS knowledge_parsed_blocks")
    op.execute("DROP TABLE IF EXISTS knowledge_uploads")
    # The additive metadata columns are intentionally retained on downgrade so
    # historical rights and provenance evidence cannot be silently discarded.
