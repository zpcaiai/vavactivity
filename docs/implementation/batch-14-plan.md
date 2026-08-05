# Batch 14 Implementation Plan — Bidirectional Recommendation Engine

Batch 14 produces safe, bidirectional, explainable and auditable recommendations from the
approved profile projections Batch 13 publishes. It does not create likes, mutual choices or
introductions — those belong to Batch 15 — and it does not own reports, blocks or fraud
handling, which belong to Batch 18.

## Module boundary

| Concern | Owner |
| --- | --- |
| Account, login, RBAC | Batch 2 identity |
| Protected date of birth, consent, field visibility | Batch 12 privacy |
| Approved dating profile, preferences, projections | Batch 13 matchmaking_profiles |
| Pool, candidates, filtering, scoring, ranking, explanations, batches, exposure, feedback | Batch 14 recommendations |
| Like, skip, withdraw, mutual choice, introductions, contact exchange | Batch 15 |
| Getting-to-know period and relationship stages | Batch 16 |
| Membership entitlements | Batch 17 |
| Reporting, blocking, safety restrictions | Batch 18 |

The engine reads `dating_profile_recommendation_projections` and nothing else from the
profile domain. Draft profiles, narratives, photos, contact details, exact birth dates,
review notes, AI conversations, counselling records and payments are not inputs.

## Delivery slices

1. **Strategy and domain model** — versioned policy documents (hard constraints, feature
   manifest, scoring, bidirectional, ranking, diversification, exposure, explanation, cold
   start), the release lifecycle, and the audit table. Migrations `0054`–`0059`.
2. **Recommendation pool** — eligibility recomputed from the projection, the account, the
   profile status, the member's own pause switch and adult eligibility, with a reason code
   for every exclusion.
3. **Canonical pairs and recall** — one `(low, high)` record per member pair, SQL recall on
   normalised columns, and a bounded candidate limit.
4. **Exclusions** — safety (fail closed), blocks, active relationships, invitations, skip
   cooldowns and privacy, applied before scoring.
5. **Hard constraints** — both directions, unknown-value policies, member-permitted
   relaxation, never-relaxable safety rules, and aggregate diagnostics.
6. **Feature registry and directional scoring** — approved features only, member importance
   as weight, `required` never double counted, missingness lowering confidence.
7. **Bidirectional composition** — minimum direction, geometric mean, asymmetry suppression,
   balance and confidence.
8. **Ranking and diversification** — deterministic seed, adjustments stored separately from
   compatibility, MMR-style spacing inside the qualified set, bounded exploration slots.
9. **Explanations** — deterministic templates, disclosure levels, information gaps,
   relaxation notices, the approved caveat, and a strictly bounded optional AI rewrite.
10. **Batches and exposure** — immutable snapshots, idempotent generation, atomic activation,
    display-time rechecks, idempotent exposure events, locked daily budgets, cooldowns and
    popularity caps.
11. **Cold start** — classification, transparent defaults, guidance, new-profile exposure and
    honest empty results.
12. **Feedback, tuning and experiments** — idempotent typed events, safety feedback removing
    candidates immediately, skip cooldowns, bounded and resettable member tuning, offline
    evaluation gating every release, and guarded experiments disabled by default.
13. **Web experience** — member list, detail, preferences, history and transparency pages, and
    the administrator supervision centre.
14. **Testing and acceptance** — unit, integration, concurrency, security, fairness and E2E.

## Non-negotiables

- A pair passes only when **both** members' hard constraints pass.
- A missing value follows the member's own unknown policy; it is never a silent failure.
- Adult eligibility, relationship eligibility, safety blocks and privacy consent are never
  relaxed, whatever a member or an operator permits.
- Scores are integer basis points, deterministic for a given snapshot and strategy.
- The member never sees a percentage, the other member's score, their criteria, their contact
  details or their exact birth date.
- Refreshing cannot buy extra recommendations; the daily budget is enforced with a lock.
- Operators supervise the engine and cannot force a pairing, edit a score or bypass a rule.
- A correctness violation in the offline evaluation blocks the release; ranking quality never
  unlocks it.

## Open decisions

Recorded in `docs/product/decision-register.md`: default feature weights, minimum score
thresholds, daily exposure limits, repeat-exposure cooldown, exploration slot count,
cold-start minimum exposure, fairness thresholds and whether experiments are ever enabled in
production.
