---
name: vav-skill-registry-dependency-graph
description: Implement or review Skill registration, version resolution, capabilities, dependency closure, cycle/conflict detection, revocation propagation, or upgrade impact analysis.
---

Resolution must be deterministic and produce a complete conflict path. Reject cycles, unresolved required capabilities, incompatible runtime/platform ranges, and revoked dependencies. Preserve the current active installation on failure. Run `make skill-registry-test`.
