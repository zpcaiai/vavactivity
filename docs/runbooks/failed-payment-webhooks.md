# Failed payment webhooks

## Symptoms and impact

Webhook signature, schema, delivery, ordering, or reconciliation fails; affected orders remain pending and no entitlement is granted.

## Detect and contain

Inspect signature/error/dead-letter metrics and provider event identity. Preserve the raw provider evidence in its restricted store, stop retry storms, and never use the browser return or an unsigned manual request as proof of payment.

## Recover and verify

Restore endpoint/secret/provider delivery, replay verified events idempotently, reconcile provider/local amounts and currencies, and run concurrency/replay tests. Verify exactly one payment transition and entitlement projection; revert intake if divergence remains.

## Rollback, communication, and review

Keep orders pending while uncertain and communicate delayed confirmation. Review signature rotation, endpoint availability, idempotency keys, ordering, alerts, and customer remediation.
