---
name: vav-batch-14-03-hard-constraint-engine
description: "Implement Hard-constraint engine for the VAV platform."
---

# Hard-constraint engine

Evaluate both directions and pass the pair only when both pass. Only criteria a
member explicitly marked hard, plus the approved platform rules (adult
eligibility, relationship eligibility), can exclude. A missing value follows the
member's own `allow_unknown` policy and is never silently treated as failure.
Relaxation needs the member's permission and the platform flag together, is
recorded so the member can be told, and can never touch adult eligibility,
relationship eligibility, safety blocks or privacy consent. Failures are
reported as criterion codes and counts — never as another member's preferences.
