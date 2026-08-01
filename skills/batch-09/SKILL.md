---
name: vav-batch-09-knowledge-rag-retrieval
description: Build authorization-gated, versioned knowledge ingestion, hybrid retrieval, provenance, evaluation and administration.
---

# Goal

Implement isolated knowledge spaces, immutable source/document versions,
explicit usage authorization, parsing, PII/secret/injection findings, semantic
chunks, profile-bound embeddings, pgvector plus full-text hybrid retrieval,
runtime ACL filtering, citations, blue-green indexes, rollback and at least 30
evaluation cases. Batch 10 owns conversation generation and orchestration.

# Mandatory invariants

- Upload or internal visibility never implies RAG or public quotation rights.
- Revoked/expired authorization disappears from retrieval immediately.
- Published versions/chunks are immutable and citations bind exact versions.
- Retrieval filters space, ACL, sensitivity, locale, region and validity again
  at query time; permission scope is part of every cache key.
- Private counseling records, learner submissions, dating profiles and AI
  conversations are excluded by default.
- Document instructions are untrusted data and never authorize tools.
- Fake embeddings are development/test only; production fails closed.
- Index activation is atomic, reversible and blocked by any ACL/auth leakage.

# Required order and gates

Read every child skill, then implement domain, authorization, ingestion,
parsing, versions, chunks, embeddings, retrieval, citations, evaluation, admin
UI and tests. Provide all `make knowledge-*` commands and recursively execute
`make counseling-verify` plus the platform gate.
