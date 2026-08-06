---
name: vav-compensation-framework
description: Run registered idempotent business compensations in reverse dependency order.
---

Compensation is not database rollback. Refund confirmed payment and preserve the payment fact; failed compensation creates intervention.
