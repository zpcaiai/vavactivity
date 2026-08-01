"""Add authorization-gated knowledge ingestion and hybrid retrieval.

Revision ID: 20260731_0028
Revises: 20260731_0027
"""

# ruff: noqa: E501

from alembic import op

revision = "20260731_0028"
down_revision = "20260731_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    statements = """
    CREATE TABLE knowledge_spaces (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), space_code varchar(128) UNIQUE NOT NULL,
      name varchar(200) NOT NULL, purpose varchar(1000) NOT NULL, status varchar(32) NOT NULL DEFAULT 'draft',
      default_locale varchar(16) NOT NULL, allowed_roles jsonb NOT NULL DEFAULT '[]',
      created_by uuid NOT NULL REFERENCES users(id), version integer NOT NULL DEFAULT 1,
      created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE knowledge_sources (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), space_id uuid NOT NULL REFERENCES knowledge_spaces(id),
      source_code varchar(128) UNIQUE NOT NULL, source_type varchar(64) NOT NULL, title varchar(300) NOT NULL,
      connector_config_encrypted text, sensitivity varchar(32) NOT NULL DEFAULT 'internal',
      status varchar(32) NOT NULL DEFAULT 'active', created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE knowledge_authorizations (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), source_id uuid NOT NULL REFERENCES knowledge_sources(id),
      status varchar(32) NOT NULL, allow_rag boolean NOT NULL DEFAULT false,
      allow_public_quote boolean NOT NULL DEFAULT false, allow_external_training boolean NOT NULL DEFAULT false,
      allowed_regions jsonb NOT NULL DEFAULT '[]', evidence_encrypted text NOT NULL,
      valid_from timestamptz NOT NULL, valid_until timestamptz, approved_by uuid REFERENCES users(id),
      revoked_at timestamptz, version integer NOT NULL DEFAULT 1, created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE knowledge_documents (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), source_id uuid NOT NULL REFERENCES knowledge_sources(id),
      document_code varchar(128) UNIQUE NOT NULL, title varchar(500) NOT NULL, locale varchar(16) NOT NULL,
      status varchar(32) NOT NULL DEFAULT 'draft', current_version_id uuid,
      created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE knowledge_document_versions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), document_id uuid NOT NULL REFERENCES knowledge_documents(id),
      version_number integer NOT NULL, status varchar(32) NOT NULL DEFAULT 'uploaded', mime_type varchar(128) NOT NULL,
      checksum_sha256 varchar(64) NOT NULL, original_storage_key_encrypted text,
      raw_text_encrypted text NOT NULL, normalized_text text NOT NULL, parsed_blocks jsonb NOT NULL DEFAULT '[]',
      parse_quality_bps integer NOT NULL DEFAULT 0, source_locator jsonb NOT NULL DEFAULT '{}',
      published_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(document_id, version_number), UNIQUE(document_id, checksum_sha256)
    );
    ALTER TABLE knowledge_documents ADD CONSTRAINT knowledge_documents_current_version_fk
      FOREIGN KEY (current_version_id) REFERENCES knowledge_document_versions(id);
    CREATE TABLE knowledge_processing_jobs (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), document_version_id uuid NOT NULL REFERENCES knowledge_document_versions(id),
      job_type varchar(32) NOT NULL, status varchar(32) NOT NULL, idempotency_key varchar(255) UNIQUE NOT NULL,
      attempts integer NOT NULL DEFAULT 0, error_code varchar(128), created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE knowledge_findings (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), document_version_id uuid NOT NULL REFERENCES knowledge_document_versions(id),
      finding_type varchar(32) NOT NULL, severity varchar(32) NOT NULL, locator jsonb NOT NULL DEFAULT '{}',
      details_encrypted text NOT NULL, blocks_publication boolean NOT NULL DEFAULT false,
      status varchar(32) NOT NULL DEFAULT 'open', created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE knowledge_embedding_profiles (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), profile_code varchar(128) UNIQUE NOT NULL,
      provider varchar(64) NOT NULL, model varchar(128) NOT NULL, dimensions integer NOT NULL CHECK(dimensions = 64),
      distance_metric varchar(32) NOT NULL DEFAULT 'cosine', status varchar(32) NOT NULL DEFAULT 'active',
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE knowledge_index_versions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), space_id uuid NOT NULL REFERENCES knowledge_spaces(id),
      version_number integer NOT NULL, embedding_profile_id uuid NOT NULL REFERENCES knowledge_embedding_profiles(id),
      chunk_strategy varchar(128) NOT NULL, status varchar(32) NOT NULL DEFAULT 'building',
      previous_index_id uuid REFERENCES knowledge_index_versions(id), evaluation_status varchar(32) NOT NULL DEFAULT 'not_run',
      activated_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(space_id, version_number)
    );
    CREATE UNIQUE INDEX knowledge_one_active_index ON knowledge_index_versions(space_id) WHERE status = 'active';
    CREATE TABLE knowledge_chunks (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), document_version_id uuid NOT NULL REFERENCES knowledge_document_versions(id),
      index_version_id uuid NOT NULL REFERENCES knowledge_index_versions(id), parent_chunk_id uuid REFERENCES knowledge_chunks(id),
      chunk_number integer NOT NULL, chunk_type varchar(32) NOT NULL, content text NOT NULL,
      content_sha256 varchar(64) NOT NULL, token_count integer NOT NULL, title_path jsonb NOT NULL DEFAULT '[]',
      source_locator jsonb NOT NULL DEFAULT '{}', allowed_roles jsonb NOT NULL DEFAULT '[]',
      sensitivity varchar(32) NOT NULL DEFAULT 'internal', injection_suspected boolean NOT NULL DEFAULT false,
      status varchar(32) NOT NULL DEFAULT 'published', search_vector tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,
      created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(index_version_id, document_version_id, chunk_number)
    );
    CREATE INDEX knowledge_chunks_fts ON knowledge_chunks USING gin(search_vector);
    CREATE TABLE knowledge_embeddings (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), chunk_id uuid NOT NULL REFERENCES knowledge_chunks(id),
      embedding_profile_id uuid NOT NULL REFERENCES knowledge_embedding_profiles(id), embedding vector(64) NOT NULL,
      content_sha256 varchar(64) NOT NULL, token_count integer NOT NULL, latency_ms integer NOT NULL DEFAULT 0,
      created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(chunk_id, embedding_profile_id)
    );
    CREATE INDEX knowledge_embeddings_hnsw ON knowledge_embeddings USING hnsw (embedding vector_cosine_ops);
    CREATE TABLE knowledge_retrieval_queries (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), space_id uuid NOT NULL REFERENCES knowledge_spaces(id),
      actor_id uuid REFERENCES users(id), permission_scope_hash varchar(64) NOT NULL, query_encrypted text NOT NULL,
      locale varchar(16) NOT NULL, result_count integer NOT NULL, no_answer boolean NOT NULL,
      latency_ms integer NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE knowledge_citations (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), retrieval_query_id uuid NOT NULL REFERENCES knowledge_retrieval_queries(id),
      document_id uuid NOT NULL REFERENCES knowledge_documents(id), document_version_id uuid NOT NULL REFERENCES knowledge_document_versions(id),
      chunk_id uuid NOT NULL REFERENCES knowledge_chunks(id), source_locator jsonb NOT NULL DEFAULT '{}',
      excerpt text, excerpt_sha256 varchar(64), availability_status varchar(32) NOT NULL DEFAULT 'available',
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE knowledge_evaluation_datasets (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), dataset_code varchar(128) UNIQUE NOT NULL,
      name varchar(300) NOT NULL, status varchar(32) NOT NULL DEFAULT 'active', created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE knowledge_evaluation_cases (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), dataset_id uuid NOT NULL REFERENCES knowledge_evaluation_datasets(id),
      case_code varchar(128) NOT NULL, category varchar(64) NOT NULL, locale varchar(16) NOT NULL,
      query text NOT NULL, expected_document_codes jsonb NOT NULL DEFAULT '[]', forbidden_document_codes jsonb NOT NULL DEFAULT '[]',
      expected_no_answer boolean NOT NULL DEFAULT false, principal_roles jsonb NOT NULL DEFAULT '[]',
      UNIQUE(dataset_id, case_code)
    );
    CREATE TABLE knowledge_evaluation_runs (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), dataset_id uuid NOT NULL REFERENCES knowledge_evaluation_datasets(id),
      index_version_id uuid NOT NULL REFERENCES knowledge_index_versions(id), status varchar(32) NOT NULL,
      total_cases integer NOT NULL, passed_cases integer NOT NULL, authorization_violations integer NOT NULL DEFAULT 0,
      acl_leakage_count integer NOT NULL DEFAULT 0, metrics jsonb NOT NULL DEFAULT '{}',
      created_at timestamptz NOT NULL DEFAULT now()
    )
    """
    for statement in statements.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    for table in (
        "knowledge_evaluation_runs",
        "knowledge_evaluation_cases",
        "knowledge_evaluation_datasets",
        "knowledge_citations",
        "knowledge_retrieval_queries",
        "knowledge_embeddings",
        "knowledge_chunks",
        "knowledge_index_versions",
        "knowledge_embedding_profiles",
        "knowledge_findings",
        "knowledge_processing_jobs",
        "knowledge_document_versions",
        "knowledge_documents",
        "knowledge_authorizations",
        "knowledge_sources",
        "knowledge_spaces",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
