---
name: vav-batch-20-skill-platform
description: Implement or review VAV Skill SDKs, manifests, schemas, runtime, registry, permissions, sandboxing, signing, compatibility, installation, CLI/API/IDE, console, Marketplace governance, red-team gates, and final certification. Use for every Batch 20 Skill-platform change.
---

# Goal

Build a governed extension platform on top of Batches 1–19 without weakening business, privacy, payment, authorization, or safety boundaries.

# Required workflow

1. Read `project-manifest.yaml`, `release-manifest.yaml`, and all Batch 20 Skills relevant to the change.
2. Keep manifests immutable, schemas strict, permissions intersected, network/files/secrets denied by default, and third-party execution outside the primary API process.
3. Implement one vertical closure at a time: specification -> tests -> runtime/storage/API/UI -> security tests -> evidence.
4. Run the specific `make skill-*-test` gate and then `make skill-verify`.
5. Preserve `NOT_CERTIFIED` when signatures, external scans, human Marketplace review, sandbox evidence, or production records are absent.

# Non-negotiable gates

- Reject unknown manifest and schema fields, wildcard authority, arbitrary shell commands, embedded credentials, dependency cycles, incompatible upgrades, unsigned production packages, revoked keys, and unreviewed public listings.
- Validate input before execution and output before delivery.
- Propagate deadlines, cancellation, idempotency, trace identity, and safe errors.
- Bind caches to concrete version, installation, actor scope, and effective permissions.
- Never let a Skill access business databases directly.

# Verification

Run `make skill-sdk-test skill-schema-test skill-runtime-test skill-registry-test skill-security-test skill-marketplace-test skill-complete-e2e`. `make final-release` may report certified only when every external and human gate has real evidence.
