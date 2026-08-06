# Failed migration

## Symptoms and impact

The migration job fails or schema revision/compatibility checks diverge; new workloads must not receive traffic.

## Detect

Read the migration job log, Alembic current/heads, locks, statement timeout, and release manifest. Do not infer success from pod rollout.

## Immediate containment

Stop rollout, keep compatible old workloads, block contract steps/backfills, snapshot evidence, and prevent a second writer from rerunning blindly.

## Recovery

Use declared rollback only if data-safe; otherwise repair forward. Re-run the empty and previous-snapshot migration gates before staging.

## Verification and rollback

Run `./scripts/database/check-migrations.sh`, table/invariant checks, old/new application compatibility, and smoke. Revert application digest if the expanded schema supports it.

## Communication and review

Report exact revision and data impact. Review lock estimate, transaction boundary, backfill cursor, and expand-migrate-contract compliance.
