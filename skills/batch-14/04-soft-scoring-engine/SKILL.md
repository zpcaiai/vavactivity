---
name: vav-batch-14-04-soft-scoring-engine
description: "Implement Soft scoring engine for the VAV platform."
---

# Soft scoring engine

Score only through the approved feature registry: code, version, group, value
schema, scoring function, sensitivity, explainability and default weight. Member
importance sets the weight; `required` is already a hard constraint and is never
counted twice. Missing information lowers confidence rather than scoring zero,
and confidence separately reflects coverage, breadth and profile readiness so a
single matching field cannot yield a confident perfect score. Scores are integer
basis points and deterministic for the same snapshots. Appearance, wealth,
health, ethnicity, personality, AI conversations, counselling records and
payment behaviour are structurally impossible inputs.
