# Batch 14 Acceptance Report — Bidirectional Recommendation Engine

Date: 2026-08-04

## Accepted scope

Batch 14 delivers the recommendation engine Phase 2 depends on:

- one versioned `recommendation_strategies` record holding every weight, threshold and policy —
  hard constraints, a 16-feature manifest, scoring, bidirectional combination, ranking,
  diversification, exposure, explanation and cold start — so a change is reviewable,
  reproducible and reversible;
- database-enforced release governance: a trigger refuses to activate a strategy without an
  approver and a passing evaluation, and a partial unique index keeps exactly one active
  strategy per code;
- a recommendation pool built solely from the Batch 13 de-identified projection, carrying coarse
  codes, buckets and versions plus the explicit reasons a member is out of the pool;
- candidate generation that recalls on normalised codes, consults a fail-closed moderation
  gateway, excludes blocked, cooled-down and already-interacting pairs, and stores one row per
  pair regardless of who asked first;
- bidirectional hard-constraint evaluation where relationship eligibility is checked both ways,
  only allow-listed criteria may exclude, a blank field is unknown rather than a failure, and
  relaxation requires the viewer's own opt-in and applies only to the viewer's own conditions;
- directional soft scoring where the member's importance overrides the platform default,
  `required` is never double-counted as a soft weight, missing information lowers confidence
  instead of scoring zero, and confidence is capped by an absolute-information floor so one
  lucky matching field can never look like a confident perfect match;
- harmonic-mean bidirectional combination floored by the weaker direction and penalised by
  imbalance, with both directions required to clear their own floor;
- deterministic seeded ranking where novelty, repeat-exposure and popularity adjustments are
  reported separately from compatibility, and maximal-marginal-relevance diversification that
  reorders qualified candidates and raises rather than ever admitting an unqualified one;
- template-only Chinese explanations with per-section caps, a standing caveat, disclosure of any
  applied relaxation, and a fail-closed `assert_safe` check that refuses to persist an
  explanation containing a criterion code, an internal weight, a directional score, a rank or a
  probability marker;
- separate daily receive and show budgets, exposure counted from real visibility rather than
  render, an expiring repeat cooldown, popularity suppression that never removes an existing
  interaction, and fairness measured only inside the qualified pool;
- cold-start classification, exploration slots drawn from the qualified pool only, a new-profile
  exposure floor, non-coercive sparse-preference guidance, and an honest empty-result
  explanation with aggregate reasons and real options;
- idempotent feedback intake with encrypted free text, safety feedback routed to the safety
  domain and never recycled as taste data, clamped weight adjustments that can never become an
  exclusion, a personalisation off-switch and a full reset;
- an offline evaluation whose five zero-tolerance safety guardrails — hard-constraint,
  eligibility, blocked-pair, privacy and safety-restriction violations — block a release
  outright, and where engagement metrics alone can never pass one;
- a member recommendation page (today's batch, settings, history, transparency) and an operator
  centre with eleven permission-gated sections.

## Verification evidence

| Gate | Result | Evidence |
| --- | --- | --- |
| Alembic | PASS | Local PostgreSQL is at `20260804_0059`; migrations `0054`–`0059` applied from a clean schema. |
| Backend tests | PASS | 517 tests pass (`pytest tests -q`), of which 169 are new Batch 14 tests. |
| Batch 14 unit | PASS | 119 tests across hard constraints, scoring, combination, ranking, explanations, exposure, cold start, feedback, domain and offline metrics. |
| Batch 14 integration | PASS | 22 tests across pool sync, candidate generation, batching, exposure, feedback and invalidation. |
| Batch 14 concurrency | PASS | 8 tests: concurrent batching, duplicate exposure and feedback keys, concurrent candidate generation, one active strategy, unapproved activation, duplicate batch member, concurrent tuning. |
| Batch 14 security | PASS | 13 tests: cross-user access, blocked pairs, fail-closed moderation, contact-detail absence, explanation non-disclosure, relaxation scope, audit content, prohibited signals, anonymous and unprivileged API access. |
| Batch 14 fairness | PASS | 7 tests: pool reachability, exposure spread, show-budget protection, conditions never overridden for fairness, guardrail gating, dataset privacy approval, zero-tolerance ceilings. |
| Ruff | PASS | `ruff check` clean; `ruff format --check` reports 371 files already formatted. |
| mypy | PASS | `mypy --strict src` — no issues in 184 source files. |
| ESLint | PASS | `pnpm -r run lint` — 0 errors across both applications. |
| vue-tsc | PASS | `pnpm -r run typecheck` — user-web, admin-web and api-client all clean. |
| OpenAPI | PASS | `packages/contracts/openapi.json` regenerated; TypeScript types rebuilt from it. |
| Offline evaluation | PASS | Clean synthetic run: see the table below. |

## Offline evaluation, clean synthetic cohort

Run against `recommendation-baseline-synthetic` (synthetic only) with an 8-member balanced
cohort, 8 generated batches and 32 recommendation items:

| Group | Metric | Value |
| --- | --- | --- |
| Correctness | hard-constraint violation rate | 0 bps |
| Correctness | eligibility violation rate | 0 bps |
| Correctness | blocked-pair leakage rate | 0 bps |
| Correctness | privacy violation rate | 0 bps |
| Correctness | safety-restriction violation rate | 0 bps |
| Correctness | self-recommendations | 0 |
| Correctness | profile-version accuracy | 10000 bps |
| Ranking | NDCG@10 | 9979 bps |
| Ranking | precision@5 | 10000 bps |
| Ranking | minimum directional score | 6516 bps |
| Coverage | profile exposure coverage | 10000 bps |
| Coverage | empty result rate | 0 bps |
| Fairness | measured within qualified candidates only | true |

The run is recorded as `recommendation.evaluation.completed` and sets `evaluation_passed` on the
strategy, which is what the activation trigger requires.

## Database-enforced invariants

These are not application conventions — each has a test that proves the database refuses the
bad write:

| Invariant | Mechanism |
| --- | --- |
| A strategy needs approval and a passing evaluation to activate | `require_recommendation_strategy_gates()` trigger |
| Exactly one active strategy per code | `uq_active_recommendation_strategy` partial unique index |
| Exactly one active batch per member | `uq_recommendation_active_batch` partial unique index |
| Nobody appears twice in one batch | `UNIQUE(recommendation_batch_id, recommended_user_id)` |
| One row per pair per version snapshot | `UNIQUE(user_low_id, user_high_id, strategy_id, …)` |
| Replay-safe exposure and feedback | `UNIQUE(viewer_user_id, idempotency_key)` |

## Safety and privacy posture

- The engine reads the Batch 13 projection and nothing else. No test could find a narrative,
  photo, contact detail, email or raw date of birth anywhere in a pool entry, candidate pair,
  score, batch item, explanation or audit row.
- Appearance, face, ethnicity, income, spend, counselling records, AI conversation content and
  spiritual or mental-health inference are registered as prohibited signals and rejected by the
  scorer, not merely absent from the manifest.
- The moderation gateway fails closed: a broken moderation store yields
  `{"allowed": false, "reason_code": "moderation_unavailable"}`, never an accidental allow.
- Explanations disclose nothing about the other person's criteria, score or rank, and carry no
  percentage or success probability.
- Safety feedback (report, block) removes the pair and is never used as preference-learning data.
- Free-text feedback reasons are encrypted at rest and never reach the other member.
- Operator diagnostics are aggregate only and name no candidate.

## Deliberate exclusions

Batch 14 stops at the contract for everything downstream:

- like, skip-as-rejection, mutual match, introductions and contact exchange — Batch 15;
- the relationship journey state machine — Batch 16;
- blocking, reporting and restriction storage — Batch 18. Until those tables exist, the gateway
  detects their absence and continues to fail closed on any error.

## Open decisions

Five entries were added to the decision register and the manifest rather than resolved in code:
faith weighting, membership benefit scope, experiment governance, daily batch size policy and
cross-region matching. In every case the code keeps the most conservative behaviour: the
criterion stays soft, experiments stay off and approval-gated, and geography uses coarse codes
only.
