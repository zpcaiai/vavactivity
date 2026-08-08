---
name: vav-batch-14-05-bidirectional-compatibility
description: "Implement Bidirectional compatibility for the VAV platform."
---

# Bidirectional compatibility

Compute A→B and B→A separately and keep both. Compose with the weaker direction
plus a geometric mean, never a plain average, and suppress strongly asymmetric
pairs so a 95/25 pair cannot pass as a 60. Record the minimum direction, the
balance score and the composition policy version. Mutual strengths require both
directions to agree; mutual unknowns are the intersection of both gaps. Direction
reversal never creates a second pair, and the other member's directional score
and preference profile never reach the viewer.
