---
name: vav-inventory-reservations
description: Implement atomic create, confirm, release and expiry of stock reservations.
---

Lock the inventory row before checking availability. Make transitions idempotent,
write movement/audit records, reject confirmation after expiry and use Celery Beat to
release elapsed active reservations.
