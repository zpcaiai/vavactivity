---
name: vav-access-decision-engine
description: Return safe membership-only capability, scope and quota decisions.
---

# Rules

- Check account, entitlement, plan version, grant, scope and quota in order.
- Fail closed with stable reason codes and no internal-policy leakage.
- Treat allowed as membership permission only; owning modules recheck resource eligibility and safety.
- Never cache a quota-consuming allow beyond the atomic consumption.
