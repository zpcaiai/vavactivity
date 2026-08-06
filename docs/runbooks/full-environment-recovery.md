# Full environment recovery

## Symptoms and impact

The primary environment is unavailable or untrusted and service must be rebuilt in a clean region/account.

## Detect

Incident command confirms primary recovery cannot meet the approved objective and identifies a verified recovery point and signed release.

## Immediate containment

Freeze primary writes/traffic, preserve forensic evidence, revoke compromised credentials, and prevent split brain.

## Recovery

Provision isolated network/data providers, restore and verify database/objects/config, issue new secrets, deploy the matching immutable release, migrate compatibly, and resume priority workers before general traffic.

## Verification and rollback

Run full integrity, smoke, complete E2E, payment reconciliation, privacy, and safety gates; verify DNS/TLS/observability/backup. Abort cutover and retain isolation on any unexplained divergence.

## Communication and review

Incident command publishes scope, RPO/RTO status, data-loss assessment, and cutover decision. Reconcile the old environment before destruction and complete a full recovery review.
