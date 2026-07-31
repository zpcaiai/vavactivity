---
name: vav-batch-07-courses-learning-progress-certificates
description: Implement or review VAV multilingual course catalogs, Catalog-linked course and bundle SKUs, versioned curriculum, secure video access, entitlement enrollment, progress, exercises, grading, completion, certificates and course administration. Use whenever work touches VAV courses or learning.
---

# Goal

Deliver the course and learning lifecycle while preserving Catalog, Commerce,
Entitlement, Media, RBAC, audit and outbox authority boundaries.

## Required reading

1. Read `project-manifest.yaml`, the decision register and Batch 7 plan.
2. Read every child `SKILL.md` in this directory.
3. Inspect Catalog fulfillment snapshots and Entitlement activation.
4. Preserve unresolved hosting, expiry, download, membership and certificate
   policies as fail-closed configuration.

## Execution order

1. Domain, publication, curriculum and immutable versions.
2. Catalog mappings, entitlement projection and access decisions.
3. Playback, monotonic progress, exercises, completion and certificates.
4. User and administration journeys.
5. Unit, integration, concurrency, security and browser acceptance.

## Invariants

- Never duplicate prices, payments or entitlement state.
- Never grant paid access from a browser payment return.
- Pin every enrollment to a published curriculum version.
- Keep original video locations, answer keys and learner private responses out
  of learner/public DTOs and ordinary logs.
- Use idempotency and monotonic rules for entitlement, progress, completion and
  certificate operations.
- Never claim that watch percentage proves attention or understanding.
- Never describe a VAV completion certificate as an official qualification.

## Verification

Run `make course-verify`; it must recurse through `make activity-verify`.

