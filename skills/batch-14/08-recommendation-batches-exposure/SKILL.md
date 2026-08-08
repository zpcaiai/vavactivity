---
name: vav-batch-14-08-recommendation-batches-exposure
description: "Implement Batches and exposure for the VAV platform."
---

# Batches and exposure

A batch is immutable and bound to the strategy, profile, preference and privacy
versions that produced it, with frozen visible-profile and explanation
snapshots. Generation is idempotent per period, so a refresh returns the same
batch and cannot buy extra recommendations. Display-time still rechecks safety,
privacy, profile status and exclusions before an item is returned. Exposure
events are idempotent; a loaded card is not a seen card until it meets the
visible threshold. Daily receive and per-profile shown limits are enforced with a
locked conditional update, repeat exposure respects the cooldown, and popularity
caps never manufacture an ineligible recommendation.
