# Batch 9 implementation plan

Authority: supplied Batch 9 knowledge/RAG specification and repository Skills.

1. Add isolated knowledge spaces, sources, documents and immutable versions.
2. Gate every processing and retrieval path with explicit, independently
   scoped authorization for RAG, quotation and external training.
3. Ingest verified private files and safe CMS/course/activity/counseling public
   projections, excluding private records and live operational facts.
4. Parse structured blocks, normalize text, record quality and block secrets.
5. Build provenance-preserving parent/child chunks and profile-bound embeddings.
6. Use pgvector plus PostgreSQL full-text search with deterministic RRF and
   query-time ACL/authorization/validity filters.
7. Bind citations to exact document/version/chunk locators and quotation rights.
8. Provide blue-green index activation/rollback and 30+ evaluation cases with
   zero-leakage gates.
9. Build RBAC-gated admin knowledge center and complete test/acceptance commands.

Embedding provider, query retention and public citation policy remain undecided.
Production therefore rejects the fake provider, query logs stay encrypted, and
public excerpts fail closed without explicit quotation authorization.
