---
name: vav-batch-18-trust-safety
description: Implement and verify the platform Trust & Safety control plane and zero-bypass release gates.
---

# Goal

Deliver confidential reporting, immediate blocking, versioned moderation/rules, scoped restrictions,
human cases and independent appeals across every business module.

# Required order

Domain/migrations -> reporting/blocking -> moderation -> harassment/fraud signals -> rule engine ->
restrictions -> cases/evidence -> appeals/remediation -> integrations -> web -> red-team acceptance.

# Non-negotiable invariants

- Blocks propagate synchronously and cannot be bypassed through URLs, activities, recommendations,
  interactions, relationships, cached grants or membership.
- Automated systems never permanently ban, diagnose or make a criminal/legal finding.
- Reporter identity and sensitive evidence remain confidential, minimized, encrypted and audited.
- Rules use registered signals and a non-executable DSL; protected attributes and private counseling
  or AI content are never risk features.
- High-impact actions use four-eyes approval; appeals use an independent reviewer and never restore
  another member's block or withdrawn consent.
- Release stays `NOT_CERTIFIED` until all zero-bypass and zero-leakage gates are measured.

# Verification

Run `make safety-verify`, full backend/frontend gates, migration-head validation and predecessor
security regressions. Preserve `NOT_RUN` for browser/runtime gates that were not executed.
