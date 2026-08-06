# Batch 18 Trust & Safety implementation

Batch 18 is the platform control plane for reports, blocks, moderation, behavioral and fraud
signals, governed risk rules, scoped restrictions, human cases and independent appeals. Business
modules consume only `TrustSafetyDecision`; they never read report descriptions, evidence or
investigation notes.

## Delivered architecture

- migrations `20260805_0077`–`0082` enforce idempotency, pair uniqueness, immutable versions,
  four-eyes separation, appeal eligibility and red-team result persistence;
- synchronous block propagation invalidates recommendations, likes and invitations, freezes
  matches and relationship journeys, revokes contact grants/tokens, cancels reminders and emits
  versioned outbox events in one transaction;
- deterministic moderation normalizes Unicode and zero-width variants, records provider/model
  revision and checksum, auto-completes only low-risk results and holds high-risk content for a
  human;
- a registered-signal DSL supports only `eq`, `gte`, `lte` and `in`; it cannot execute Python,
  shell code or SQL and excludes religion, nationality, race and private counseling/AI content;
- high-impact restrictions and rule activation require a different approver; independent appeal
  review supersedes history and never restores another member's block or old contact consent;
- API, Celery, user safety centre, admin operations centre, RBAC, seeds and release tests share
  the same fail-closed policy.

## Explicit boundaries

The platform does not claim criminal, medical or legal findings and cannot replace emergency
services. Automatic systems cannot permanently ban a member. Classifier quality thresholds,
provider selection, evidence retention and the external red-team acceptance owner remain
fail-closed product/security decisions in `project-manifest.yaml`.
