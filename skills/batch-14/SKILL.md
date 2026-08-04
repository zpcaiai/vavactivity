---
name: vav-batch-14-recommendation-engine
description: Implement the complete VAV bidirectional recommendation engine — versioned strategy, candidate pool, hard-constraint filtering, directional scoring, bidirectional combination, ranking and diversification, template explanations, exposure budgets, cold start, bounded feedback personalisation, operator tooling and offline evaluation.
---

# Goal

Implement Batch 14 in the order recorded in `docs/implementation/batch-14-plan.md`.

Turn the Batch 13 de-identified recommendation projection into a daily batch of mutually
qualified people, with every weight and threshold held in one versioned, approvable,
reversible strategy record; hard constraints enforced in both directions; scores that lower
confidence rather than inventing certainty; template-only explanations that never disclose the
other person; exposure budgets and fairness measured inside the qualified pool; and an offline
evaluation whose safety guardrails — not engagement — decide whether a release ships.

# Prerequisites

1. Read `project-manifest.yaml`.
2. Verify Batch 1 through Batch 13; `make dating-profile-verify` must still pass.
3. Read every skill under `skills/batch-14`.
4. Inspect the Batch 13 projection contract, the Privacy, RBAC, Audit and Outbox contracts,
   and the moderation gateway placeholder that Batch 18 will own.
5. Record unresolved gender-eligibility, faith-weighting, membership-tier and experiment
   policies in `docs/product/decision-register.md`.

# Architecture constraints

- The engine reads the Batch 13 projection only — never a raw profile, narrative or photo.
- Every weight, threshold and policy lives in a versioned strategy record.
- A strategy needs an approver and a passing evaluation before activation (database-enforced).
- Exactly one strategy per code may be active; exactly one batch per member may be active.
- A candidate pair has one row regardless of who asked first.
- Scoring, combination, ranking and explanation are pure functions, unit-testable without a database.
- Like, mutual match and introductions belong to Batch 15; this batch stops at the contract.
- Moderation is a gateway call that fails closed.

# Eligibility invariants

- Both members must qualify for each other; relationship eligibility is checked both ways.
- Only criteria on the approved hard-constraint allow-list may exclude anyone.
- A blank field is unknown; the member decides whether unknowns are acceptable.
- Relaxation needs the viewer's opt-in, applies only to the viewer's own conditions and is disclosed.
- Adult eligibility, relationship eligibility and safety blocks are never relaxable.
- Suspended, paused, deletion-pending and invisible members leave the pool immediately.

# Scoring invariants

- `required` is a hard constraint and is never re-counted as a soft weight.
- Missing information lowers confidence; it is never scored as zero.
- A single matching field can never produce a confident perfect score.
- Prohibited signals are rejected by the scorer, not merely absent from the manifest.
- A lopsided pair never presents as a comfortable average.
- Both directions must clear their own floor, not only the combined score.
- Identical inputs always produce identical scores.

# Ranking invariants

- Ranking is deterministic for a fixed strategy, candidate snapshot and seed.
- Exposure and popularity adjustments are reported separately from compatibility.
- Diversification reorders qualified candidates; it can never admit an unqualified one.
- A per-city cap must never return an under-filled batch.

# Explanation invariants

- Sentences come from an approved template set; nothing is generated freely.
- The other party's criteria, directional score, internal weights and rank are never disclosed.
- No percentage, probability or success prediction is ever shown.
- Gaps are phrased without blame; unexplainable features never reach a member.
- Every card carries the caveat that a recommendation is an opportunity, not a guarantee.
- An applied relaxation is always disclosed to the viewer.

# Exposure and fairness invariants

- Receiving and being shown are separate daily budgets.
- A rendered card is not an exposure; visibility duration decides.
- Repeat exposure has an expiring cooldown; popularity is suppressed, never removed.
- Fairness is measured among qualified candidates only.
- Membership may never affect another person's constraints, safety or privacy.

# Feedback invariants

- Safety feedback removes the pair and is never used as taste data.
- A skip is a cooldown, not a permanent rejection.
- Learned adjustments are clamped far below anything that could act as an exclusion.
- Free-text reasons are encrypted and never shown to the other member.
- Personalisation can be switched off and every learned adjustment reset.
- Exposure and feedback writes are idempotent.

# Evaluation invariants

- Evaluation runs on a synthetic dataset; real data requires privacy approval first.
- Zero-tolerance guardrails (hard constraint, eligibility, blocked-pair, privacy, safety)
  block a release outright.
- Engagement metrics alone can never pass a release.
- A failed evaluation is recorded as `recommendation.release.blocked`.

# Required commands

```bash
make recommendation-migrate
make recommendation-seed
make recommendation-seed-fixtures
make recommendation-test
make recommendation-concurrency-test
make recommendation-security-test
make recommendation-fairness-test
make recommendation-eval
make recommendation-user-e2e
make recommendation-admin-e2e
make recommendation-verify
```

# Failure policy

When a weighting or eligibility policy is unresolved: record it in the decision register, keep
the criterion soft, use the most restrictive privacy default, invent no permanent social or
theological policy, and continue with unrelated capabilities.

When a hard-constraint test fails: stop the release, invalidate every affected candidate and
batch, identify the missing direction or allow-list check, fix the constraint evaluator, add a
regression test and rerun the recommendation and profile suites.

When a disclosure test fails: invalidate the affected explanations, remove the leaking field
from the template inputs, re-run `assert_safe` across every stored explanation, add a
regression test and rerun the security suite.

When the moderation gateway errors: fail closed, recommend nobody through that path, alert
operations, and never fall back to "allow" while the store is unavailable.

When an evaluation guardrail fails: block the release, keep the previous strategy active,
record the failing metric on the run, and do not activate anything until the guardrail passes.
