# Database unavailable

## Symptoms and impact

Readiness fails, connection/timeout alerts fire, and transactional/API/worker writes stop. Redis and provider success do not make the service writable.

## Detect

Check `/health/ready`, database provider health, connection-pool saturation, locks, replica lag, and recent release/migration evidence.

## Immediate containment

Enable a read-only maintenance message through an independently approved change, stop high-volume producers, preserve queues, and do not redirect writes to an unverified replica.

## Recovery

Restore provider connectivity or promote only a verified replica; validate schema head and consistency, then restart constrained workers before general traffic.

## Verification and rollback

Run `./scripts/vavctl smoke`, payment reconciliation, outbox recovery, privacy/safety checks, and core E2E. If unstable, re-enter maintenance and restore the last verified topology.

## Communication and review

State affected write paths, start time, data-loss assessment, recovery point, and next update. Preserve traces and complete a capacity/failover postmortem.
