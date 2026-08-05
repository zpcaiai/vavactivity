# Recommendation pipeline

Batch 14 turns Batch 13's approved profile projections into bidirectional,
explainable, auditable recommendations. Every stage is separate, versioned and
independently testable, and no stage may widen what an earlier stage allowed.

## Stages

```text
recommendation pool eligibility
  → coarse recall (SQL, normalised columns only)
  → safety / block / relationship / cooldown exclusions
  → bidirectional hard-constraint filter
  → directional soft scoring (both directions)
  → bidirectional composition and minimum thresholds
  → stable ranking, novelty, exposure and diversification
  → rule-backed explanation
  → immutable batch freeze and atomic activation
  → display-time recheck
```

The pipeline never reads a draft profile, a narrative, a photo, a contact
detail, an exact birth date, a review note, an AI conversation, a counselling
record or a payment. Its only profile input is
`dating_profile_recommendation_projections`.

## Inputs and versions

| Input | Source | Version recorded on |
| --- | --- | --- |
| Approved profile projection | Batch 13 | pool entry, candidate pair, batch, item |
| Partner preference criteria | Batch 13 | candidate pair, directional score |
| Privacy settings | Batch 12 | pool entry, batch, item |
| Strategy policies | `recommendation_strategies` | candidate pair, batch |
| Feature registry | `recommendation_feature_definitions` | directional score |

A result can always be reproduced from the stored snapshots, and a version
change invalidates rather than silently reuses.

## Tables

| Table | Purpose |
| --- | --- |
| `recommendation_strategies` | Versioned policy documents and the release lifecycle |
| `recommendation_feature_definitions` | The approved, explainable feature registry |
| `recommendation_pool_entries` | Who may be recommended, and why not |
| `recommendation_candidate_pairs` | One canonical record per member pair |
| `recommendation_directional_scores` | A→B and B→A, kept separately |
| `recommendation_pair_exclusions` | Safety, relationship and cooldown exclusions published by other batches |
| `recommendation_batches` / `recommendation_items` | Immutable delivery snapshots |
| `recommendation_rank_results` | Adjustments kept apart from compatibility |
| `recommendation_exposures` / `..._exposure_budgets` / `..._profile_exposure_stats` | What was actually seen, and the limits |
| `recommendation_feedback_events` / `..._user_tuning_profiles` / `..._user_settings` | Feedback and member control |
| `recommendation_evaluation_datasets` / `..._runs` | Offline evaluation and release gating |
| `recommendation_experiments` / `..._assignments` | Guarded experiments, disabled by default |
| `recommendation_audit_events` | Codes, versions, decisions and actors only |

## Failure behaviour

- Moderation unavailable → the pair is not recommended (`RECOMMENDATION_FAIL_CLOSED_ON_MODERATION_ERROR` cannot be turned off).
- No active strategy → the API returns 503 rather than falling back to defaults.
- No qualified candidate → an honest empty result with aggregate diagnostics.
- Recommendation failure never blocks profile editing, review, or any other service.
