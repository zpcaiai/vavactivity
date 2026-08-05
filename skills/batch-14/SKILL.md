---
name: vav-batch-14-bidirectional-recommendation-engine
description: Implement VAV candidate filtering, hard constraints, soft scoring, bidirectional compatibility, explainable ranking, recommendation batches, exposure controls, cold start, feedback learning and recommendation administration.
---

# Goal

Build a production-oriented matchmaking recommendation system containing:

- recommendation-pool eligibility;
- approved-profile projection consumption;
- candidate generation;
- safety, privacy and relationship exclusions;
- explicit hard-constraint filtering;
- unknown-value policies;
- user-controlled relaxation;
- feature definitions;
- directional soft scoring;
- bidirectional compatibility;
- confidence scoring;
- stable ranking;
- diversified recommendation lists;
- rule-backed explanations;
- immutable recommendation batches;
- exposure budgets;
- repeat-exposure cooldowns;
- popularity caps;
- cold-start exploration;
- feedback-event ingestion;
- controlled user-level tuning;
- offline recommendation evaluation;
- guarded experiments;
- user-web recommendation pages;
- admin-web recommendation operations;
- unit, integration, concurrency, security, fairness and E2E tests.

# Source requirements

The project plan requires:

- partner-preference filtering;
- recommendation lists;
- user choice after recommendations;
- mutual choice and introduction workflows;
- profile privacy and safety;
- administration support.

This batch implements filtering and recommendation. Likes, skips, mutual
choice and introduction invitations belong to Batch 15.

# Prerequisites

Before implementation:

1. Read `project-manifest.yaml`.
2. Verify Batch 1 through Batch 13.
3. Verify Batch 13 with `make dating-profile-verify`.
4. Read every skill under `skills/batch-14`.
5. Inspect Dating Profile, Privacy, Moderation, Relationship, Membership,
   RBAC, Audit, Outbox and Notification contracts.
6. Produce `docs/implementation/batch-14-plan.md`.
7. Produce `docs/architecture/recommendation-pipeline.md`.
8. Produce `docs/architecture/bidirectional-scoring.md`.
9. Produce `docs/recommendations/feature-registry.md`.
10. Record unresolved default weights, exposure limits, cold-start and
    fairness policies in the decision register.

# Required implementation order

1. Recommendation strategy and domain models.
2. Recommendation-pool projection.
3. Pair normalization and candidate generation.
4. Privacy, moderation and relationship exclusions.
5. Hard-constraint engine.
6. Unknown-value and relaxation policies.
7. Feature registry.
8. Directional soft scoring.
9. Bidirectional score composition.
10. Stable ranking.
11. Diversification and novelty.
12. Rule-backed explanations.
13. Recommendation-batch generation.
14. Exposure tracking and budgets.
15. Cold-start and exploration.
16. Feedback-event ingestion.
17. User-level tuning.
18. Offline evaluation and guardrails.
19. Experiment infrastructure.
20. User-web recommendation experience.
21. Admin-web recommendation center.
22. Unit, integration, concurrency, security, fairness and E2E tests.

# Architecture constraints

- Recommendation input comes only from approved recommendation projections.
- Draft profiles and private source entities are not recommendation input.
- Candidate generation, hard filtering, scoring, ranking and exposure remain
  separate stages.
- Every stage must be versioned and independently testable.
- Recommendation pairs use one canonical pair identity.
- Recommendation results must be reproducible from stored snapshots.
- Current safety and privacy status must be rechecked before display.
- Recommendation failure must not affect profile editing or other platform
  services.
- AI availability must not be required for baseline recommendation.

# Eligibility invariants

- Both users must have active eligible profiles.
- Both users must satisfy adult eligibility.
- Both users must permit recommendation participation.
- Suspended, deleted or safety-restricted users are excluded.
- Users cannot be recommended to themselves.
- Blocked pairs are excluded.
- Existing active relationship journeys are excluded.
- Eligibility changes invalidate unexposed recommendations.
- Moderation-service failure fails closed.

# Hard-constraint invariants

- Both users' hard constraints are evaluated.
- A pair passes only when both directions pass.
- Only explicit user hard criteria and approved platform eligibility rules
  cause hard exclusion.
- Unknown values follow the user's explicit unknown policy.
- Missing data is not automatically treated as failure.
- Hard constraints are not relaxed without explicit permission.
- Safety, adult eligibility, block and relationship-object rules are never
  relaxed.
- Constraint failures do not expose another user's private preferences.

# Scoring invariants

- Soft scores use only approved feature definitions.
- User importance settings determine user-specific weights.
- Required criteria are not counted twice as soft preferences.
- Missing values lower confidence rather than automatically scoring zero.
- Directional scores are calculated separately.
- Scores use integer basis points.
- The same snapshots and strategy produce the same score.
- Payment, counseling, AI conversation and private moderation data are not
  scoring features.
- Photo-attractiveness, health, wealth, race and personality inference are
  prohibited in the baseline feature registry.

# Bidirectional invariants

- A-to-B and B-to-A scores remain distinct.
- A strong one-sided score cannot hide an unacceptable reverse score.
- Bidirectional composition declares minimum-direction and balance policies.
- Pair direction reversal does not create another candidate-pair entity.
- User-facing explanations do not reveal the other user's private
  directional score or preference profile.
- Bidirectional policy versions are recorded.

# Ranking invariants

- Ranking uses an explicit versioned policy.
- Ranking adjustments remain separate from compatibility scores.
- Stable batch inputs produce stable ordering.
- Diversification cannot bypass hard constraints.
- Exploration cannot bypass safety, privacy or minimum scores.
- Administrative users cannot manually force a pair into a batch.
- Membership may affect access quantity but cannot bypass another user's
  conditions.

# Explanation invariants

- Explanations derive from evaluated features and approved templates.
- Explanations cannot add unsupported facts.
- Explanations cannot reveal hidden preferences or internal weights.
- Information gaps and uncertainty are shown.
- Recommendations are not represented as guarantees or marriage
  probabilities.
- Optional AI rewriting receives only approved explanation items and must
  fall back to deterministic templates.

# Batch and exposure invariants

- Batches bind to profile, preference, privacy and strategy versions.
- A user has at most one active batch for the same batch type and period.
- Batches store immutable visible-profile and explanation snapshots.
- Display-time safety and privacy rechecks still apply.
- Exposure events are idempotent.
- Loaded cards and actually visible cards are distinguished.
- Daily receiver and shown-profile limits are concurrency safe.
- Refreshing cannot bypass daily limits.
- Repeated exposure respects cooldown policy.
- Popularity limits do not create ineligible recommendations.

# Cold-start invariants

- Cold-start uses explicit profiles and preferences.
- AI conversations, counseling records and payment behavior are not cold-start
  inputs.
- Sparse preferences use transparent defaults.
- Exploration candidates still satisfy all mandatory checks.
- Users can add preferences rather than being forced to disclose every
  sensitive field.
- Empty eligible candidate sets return honest empty results.
- The system does not silently rewrite user preferences.

# Feedback invariants

- Feedback events are idempotent.
- Skips, blocks, reports and matches remain distinct.
- A skip does not silently become a permanent hard constraint.
- Blocks and reports immediately remove affected candidates.
- Negative-reason details remain private.
- Feedback-derived adjustments remain explainable and resettable.
- Users may disable behavioral personalization.
- Online feedback does not directly mutate production strategies.
- Strategy updates require offline evaluation and release.

# Experiment and fairness invariants

- Experiments pin strategy and assignment versions.
- Experiment assignment is stable.
- Safety, privacy, report and block metrics are guardrails.
- Click and like rates are not sufficient success metrics.
- Experiment variants cannot violate hard constraints.
- Exposure analysis compares qualified populations.
- Exposure balancing does not force unsuitable recommendations.
- Failed guardrails block activation or expansion.
- Production experiments remain disabled until explicitly approved.

# Security invariants

- Users access only their own batches and recommendation items.
- Contact details and exact birth dates never appear in recommendation DTOs.
- Other users' full partner preferences remain private.
- Admin diagnostics require RBAC.
- Sensitive candidate diagnostics require separate permission.
- User and administrator caches remain isolated.
- Logs and metrics do not contain sensitive profile values.
- All strategy, batch, rebuild, experiment and invalidation actions are
  audited.

# Required commands

The batch must support:

```bash
make recommendation-migrate
make recommendation-seed
make recommendation-seed-evaluations
make recommendation-build-pool
make recommendation-generate-fixtures
make recommendation-test
make recommendation-concurrency-test
make recommendation-security-test
make recommendation-fairness-test
make recommendation-eval
make recommendation-user-e2e
make recommendation-admin-e2e
make recommendation-verify
```

# Completion requirements

The batch is incomplete unless:

1. Eligible approved profiles enter the recommendation pool.
2. Ineligible and blocked profiles do not enter recommendations.
3. Candidate-pair generation is canonical and idempotent.
4. Both users' hard constraints are enforced.
5. Unknown-value policies work.
6. Prohibited constraints cannot be relaxed.
7. Directional soft scores work.
8. Missing information lowers confidence.
9. Bidirectional score composition works.
10. Strong one-sided pairs are handled safely.
11. Ranking is stable.
12. Diversification respects hard constraints.
13. Recommendation explanations are accurate and privacy preserving.
14. Batches bind to immutable versions.
15. Display-time safety and privacy rechecks work.
16. Exposure budgets are concurrency safe.
17. Repeated exposure cooldown works.
18. Popularity caps work.
19. Cold-start users can receive qualified recommendations.
20. Empty candidate sets return honest empty results.
21. Feedback events are deduplicated.
22. Blocks and reports remove candidates immediately.
23. Users can disable or reset behavioral personalization.
24. Evaluation detects hard-constraint violations.
25. Evaluation detects privacy and block leakage.
26. Qualified exposure and cold-start tests pass.
27. Failed strategy guardrails block activation.
28. User recommendation E2E tests pass.
29. Admin recommendation E2E tests pass.
30. Recommendation security tests pass.
31. Recommendation concurrency tests pass.
32. Recommendation fairness tests pass.
33. `make dating-profile-verify` still succeeds.
34. `make privacy-verify` still succeeds.
35. `make notification-verify` still succeeds.
36. `make ai-verify` still succeeds.
37. `make knowledge-verify` still succeeds.
38. `make counseling-verify` still succeeds.
39. `make course-verify` still succeeds.
40. `make activity-verify` still succeeds.
41. `make commerce-verify` still succeeds.
42. `make catalog-verify` still succeeds.
43. `make cms-verify` still succeeds.
44. `make auth-verify` still succeeds.
45. `make verify` still succeeds.

# Failure policy

When a scoring weight or recommendation policy is unresolved:

1. record it in the decision register;
2. use the approved transparent baseline;
3. keep the policy versioned and configurable;
4. do not invent a scientific compatibility claim;
5. continue implementing unrelated recommendation capabilities.

When a hard-constraint test fails:

1. stop recommendation delivery;
2. invalidate affected candidate pairs and batches;
3. identify the direction, criterion and version error;
4. repair filtering;
5. add a regression test;
6. rerun security, constraint and batch suites.

When a privacy or blocked-pair test fails:

1. stop the affected release;
2. invalidate all affected batches and caches;
3. inspect candidate generation, display-time checks and exposure records;
4. repair the backend boundary;
5. add a release-blocking regression test.

When exposure concurrency fails:

1. stop batch dispatch;
2. preserve competing exposure traces;
3. identify the missing lock, uniqueness constraint or budget transaction;
4. fix the root cause;
5. rerun exposure and fairness suites.

When an experiment guardrail fails:

1. stop or do not start the treatment;
2. preserve assignments and outcome data;
3. return affected users to the control strategy where safe;
4. investigate the failed guardrail;
5. require a new approved experiment version before restarting.
