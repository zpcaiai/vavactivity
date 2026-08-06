---
name: vav-quality-release-gates
description: Define, approve, execute, reproduce, or diagnose blocker, required and advisory quality gates and Go/No-Go decisions.
---

Allow only `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `contains`, `all_passed`, and `none_open`; reject arbitrary Python, SQL and shell. Missing current evidence fails closed. Any Blocker failure is `NO_GO`; valid Required Waivers yield `CONDITIONAL_GO`, which production does not accept.
