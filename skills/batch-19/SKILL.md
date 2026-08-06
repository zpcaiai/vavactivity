---
name: vav-batch-19-production-assembly
description: Assemble, configure, containerize, deploy, observe, back up, restore, performance-test and fully accept the complete VAV platform.
---

# Goal

Integrate Batches 1–18 as one production-shaped system with closed-world manifests, six typed environments, secret references, local and production runtimes, hardened deployment, safe migrations, supply-chain evidence, observability, backup/restore, capacity and disaster-recovery tests, complete E2E, and one-command acceptance.

# Required order

Manifest -> environment/secrets -> Compose -> production deployment -> migration -> CI/supply chain -> observability -> backup/restore -> performance -> disaster recovery -> complete E2E -> one-click acceptance.

# Invariants

- PostgreSQL is business truth; Redis and caches are reconstructable.
- Production uses immutable signed digests, non-root/read-only workloads, TLS, external secrets and default-deny networks.
- Migrations follow expand-migrate-contract and pass empty plus previous-snapshot upgrades.
- Payment uncertainty, privacy, authorization and safety always fail closed; flags cannot bypass them.
- Backup success is not restore success, and local technical PASS is not production certification.

# Verification

Run `make manifest-check config-check migration-check contract-test system-test complete-e2e`, backend/frontend/security gates, backup verification, isolated restore drill, performance smoke, and `make production-readiness`. Preserve `NOT_CERTIFIED` until every named external evidence and independent approval gate passes.
