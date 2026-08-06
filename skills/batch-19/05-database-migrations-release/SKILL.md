---
name: vav-database-migrations-release
description: Plan, validate and release VAV schema migrations and resumable backfills without unsafe downtime or data loss.
---

Use expand-migrate-contract, one Alembic head, bounded locks, explicit ownership, rollback/forward-fix notes, and resumable idempotent backfill cursors. `./scripts/database/check-migrations.sh` must upgrade both an empty database and revision-0082 snapshot. Back up before production, prevent multiple migration writers, and never contract until old workloads and backfills are gone. On failure stop rollout, preserve logs and prefer reviewed forward repair when downgrade risks data.
