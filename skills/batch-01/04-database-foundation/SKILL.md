---
name: vav-database-foundation
description: Create the PostgreSQL and Alembic base schema.
---

Enable pgcrypto, vector and citext. Create metadata, settings, outbox, idempotency and append-only audit tables with UUIDs, TIMESTAMPTZ values and optimistic versions. Every schema change requires reversible Alembic operations.

