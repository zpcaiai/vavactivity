# Staging deployment

Staging deploys the production-shaped Kubernetes overlay with staging-only secret references and hostnames. Build signed immutable images first; never retag an existing release. The `Deploy Staging` workflow requires an immutable release-manifest artifact and an environment-scoped kubeconfig.

Before traffic, run the migration dry-run against a disposable snapshot, apply the migration job once, wait for API/worker rollout, and verify `/health/startup`, `/health/ready`, and the staging smoke journey. Then run complete E2E, payment idempotency, privacy, block propagation, and red-team core evidence. A staging failure blocks promotion and does not authorize a production exception.

Rollback switches application digests to the previous compatible release. Database rollback is used only when the migration metadata explicitly declares it safe; otherwise use forward repair.
