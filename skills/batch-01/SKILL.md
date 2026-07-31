---
name: vav-batch-01-project-foundation
description: Build the runnable foundation of the VAV relationship service platform.
---

# Goal

Create a production-oriented, locally runnable monorepo containing FastAPI, two Vue 3 applications, PostgreSQL with pgvector, Redis, Celery, MinIO, Mailpit, Docker Compose, a generated OpenAPI TypeScript client, CI quality gates, and one-command verification.

# Required execution order

1. Read `project-manifest.yaml`.
2. Read every skill below this directory.
3. Implement one skill at a time and run its focused checks.
4. Run `make verify` after all focused checks pass.

# Architecture constraints

- Use a modular monolith.
- Keep AI unavailable without breaking core business services.
- Keep permissions and payments authoritative on the backend.
- Never hard-code an undecided product decision or commit credentials.
- Apply every database change through Alembic.
- Keep user and admin applications independently deployable.
- Generate shared API contracts from FastAPI OpenAPI.

# Completion requirements

The batch is complete only when bootstrap, development startup, tests, verification, clean-machine documentation and real implementations all pass.

# Failure policy

Record uncertainty in `docs/product/decision-register.md`, choose the least destructive configurable behavior, and continue only with infrastructure that does not depend on the unresolved decision.

