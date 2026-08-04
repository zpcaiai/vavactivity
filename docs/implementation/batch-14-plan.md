# Batch 14 Implementation Plan — Bidirectional Recommendation Engine

Batch 14 turns the de-identified projection that Batch 13 publishes into a daily batch of
mutually qualified people. It is the first module that decides *who a member sees*, so every
decision it makes is versioned, reproducible, explainable and reversible.

## Module boundary

| Concern | Owner |
| --- | --- |
| Account, login, RBAC | Batch 2 identity |
| Protected date of birth, consent, field visibility | Batch 12 privacy |
| Dating profile, preferences, photos, review, projections | Batch 13 matchmaking_profiles |
| Candidate pool, hard filtering, scoring, ranking, explanations, exposure | Batch 14 recommendations |
| Like, skip, mutual match, introductions, contact exchange | Batch 15 |
| Relationship journey state machine | Batch 16 |
| Reporting, blocking, restrictions, fraud | Batch 18 |

The engine reads the Batch 13 projection and nothing else. It never opens a raw profile, a
narrative, a photo, a payment record, a counseling note or an AI conversation.

## Delivery slices

1. **Domain and versioned strategy** — batch/item/pair state machines, pair normalisation,
   prohibited-signal and never-relaxable registries, and one `recommendation_strategies` row
   holding every weight, threshold and policy. Activation requires an approver and a passing
   evaluation, enforced by a trigger; a partial unique index keeps exactly one active strategy.
2. **Candidate pool** — projection-driven pool entries carrying coarse codes, buckets and
   versions plus the reasons a member is out. Account, profile, privacy and pause changes sync
   the entry immediately.
3. **Candidate generation** — code-based recall, a fail-closed moderation gateway, exclusion of
   blocked, cooled-down and already-interacting pairs, bidirectional hard-constraint evaluation
   and a stored snapshot of the versions each decision was made from.
4. **Hard constraints** — an approved allow-list, both directions evaluated, unknown handled by
   the member's own `allow_unknown`, relaxation gated on the viewer's opt-in and limited to the
   viewer's own conditions, and aggregate-only diagnostics.
5. **Directional scoring** — a 16-feature manifest mapped to projection fields, member
   importance overriding platform defaults, `required` excluded from soft weighting, missing
   data lowering confidence, and confidence capped by an absolute-information floor.
6. **Bidirectional combination** — harmonic mean floored by the weaker direction and penalised
   by imbalance, symmetric, with mutual strengths, asymmetries and mutual unknowns extracted for
   the explanation layer. Both directions must clear their own floor.
7. **Ranking and diversification** — deterministic seeded jitter, novelty / repeat / popularity
   adjustments reported separately from compatibility, stable sort, and maximal-marginal-relevance
   diversification that reorders qualified candidates and can never admit one.
8. **Explanations and transparency** — an approved Chinese template set, per-section caps, the
   standing caveat, `assert_safe` as a fail-closed disclosure check, and a member-facing
   transparency view listing what is used, what never is and what cannot be seen.
9. **Exposure budgets and fairness** — separate receive and show budgets, visibility-based
   exposure counting, repeat cooldown, popularity suppression, and fairness measured only
   inside the qualified pool.
10. **Cold start and exploration** — cold-start classification, exploration slots drawn from
    the qualified pool, new-profile exposure floor, non-coercive sparse-preference guidance and
    an honest empty-result explanation.
11. **Feedback and bounded personalisation** — idempotent feedback intake, encrypted free text,
    safety routing that never becomes taste data, clamped weight adjustments, cooldowns, a
    personalisation off-switch and a full reset.
12. **Member and operator web, offline evaluation, tests** — the member recommendation page,
    the operator centre, and unit / integration / concurrency / security / fairness suites plus
    member and operator e2e specs.

## Data model

Migrations `20260804_0054`–`20260804_0059`:

| Migration | Tables |
| --- | --- |
| 0054 | `recommendation_strategies`, `recommendation_features`, `recommendation_strategy_audit` |
| 0055 | `recommendation_pool_entries`, `recommendation_candidate_pairs`, `recommendation_directional_scores` |
| 0056 | `recommendation_batches`, `recommendation_items`, `recommendation_rank_results` |
| 0057 | `recommendation_exposures`, `recommendation_exposure_budgets`, `recommendation_skip_cooldowns` |
| 0058 | `recommendation_feedback_events`, `recommendation_user_tuning_profiles` |
| 0059 | `recommendation_evaluation_datasets`, `recommendation_evaluation_runs`, `recommendation_experiments`, `recommendation_audit_events` |

Database-enforced invariants rather than application-only checks:

- `require_recommendation_strategy_gates()` — activation needs `approved_by` and `evaluation_passed`.
- `uq_active_recommendation_strategy` — one active strategy per code.
- `uq_recommendation_active_batch` — one active batch per member.
- `UNIQUE(recommendation_batch_id, recommended_user_id)` — nobody appears twice in a batch.
- `UNIQUE(user_low_id, user_high_id, strategy_id, …versions)` — one row per pair per snapshot.
- `UNIQUE(viewer_user_id, idempotency_key)` on exposures and feedback — replay-safe writes.

## Configuration

27 `RECOMMENDATION_*` settings in `.env.example`. Three are safety invariants that must never be
flipped in a deployed environment: `RECOMMENDATION_HARD_CONSTRAINT_AUTO_RELAX=false`,
`RECOMMENDATION_FAIL_CLOSED_ON_MODERATION_ERROR=true` and
`RECOMMENDATION_REQUIRE_ZERO_BLOCKED_PAIR_LEAKAGE=true`. The settings validator refuses to boot
on an unsafe combination, and it also refuses a minimum bidirectional score below the minimum
directional score.

## What Batch 14 deliberately does not do

- No like, skip-as-rejection, mutual match, introduction or contact exchange — Batch 15.
- No relationship state machine — Batch 16.
- No blocking, reporting or restriction storage — Batch 18 owns those tables; this batch calls a
  gateway that fails closed until they exist.
- No online model that rewrites user-facing logic. The first release learns by reviewed rules
  and offline re-estimation, and the prerequisites for any model stage are recorded in code.
