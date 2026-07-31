---
name: vav-subscription-billing
description: Implement VAV recurring AI or membership subscriptions, auditable billing cycles, renewals, past-due states, grace periods and cancellation. Use for recurring payment lifecycle changes.
---

# Workflow

Record every billing period as an auditable order or billing-cycle record.
Extend entitlement periods once per verified renewal. Represent failed renewal
as `past_due`, never paid. Make cancellation policy configurable; default to
period-end cancellation while immediate cancellation is legally undecided.
Reconcile Provider and internal subscription state.
