---
name: vav-batch-14-01-recommendation-domain-model
description: "Implement Recommendation domain model for the VAV platform."
---

# Recommendation domain model

Model strategies, candidate pairs, scores, batches, items, exposures, feedback,
tuning, evaluations and experiments as separate versioned tables. A strategy
carries every policy document — hard constraints, feature manifest, scoring,
bidirectional composition, ranking, diversification, exposure, explanation and
cold start — so a rollback is re-activating a previous version, never a code
change. A candidate pair has one canonical `(low, high)` identity derived from
the identifiers themselves, so reversing the arguments cannot create a second
record. Every stored result keeps the profile, preference, privacy and strategy
versions that produced it.
