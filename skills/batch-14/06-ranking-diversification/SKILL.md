---
name: vav-batch-14-06-ranking-diversification
description: "Implement Ranking and diversification for the VAV platform."
---

# Ranking and diversification

Rank deterministically from a fixed seed, candidate snapshot and versioned
policy, so refreshing a batch cannot reshuffle it. Keep novelty, diversity,
exposure and exploration adjustments separate from the compatibility score, and
store the snapshot that produced each position. Diversify on city, region,
interests, lifestyle and profile novelty within the already-qualified set only —
no adjustment can create a recommendation that failed a hard constraint, a
safety check or the minimum scores. Final ranks are unique and contiguous, and
no operator can force a pair into a position.
