---
name: vav-account-restrictions-enforcement
description: Compose minimal-scope time-bounded restrictions across platform capabilities.
---

Use the union of active restrictions and the narrowest sufficient scope. Propagate versions through
outbox events, revoke no-longer-valid grants, require second approval for permanent/long/high-impact
actions, and never let expiry of one restriction remove another.
