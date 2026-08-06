# Payment provider failure

## Symptoms and impact

Payment creation/webhooks time out or signatures fail. Orders remain pending; entitlements must not activate from a browser return.

## Detect

Inspect provider health, webhook delay/signature/replay metrics, pending order age, and reconciliation differences.

## Immediate containment

Stop aggressive retries, display pending status, retain signed payload evidence, and block manual entitlement grants outside the governed adjustment flow.

## Recovery

Restore provider access, replay verified webhooks idempotently, reconcile provider/local ledgers, and apply refunds/entitlements through domain services.

## Verification and rollback

Run webhook replay/concurrency tests, confirm totals/currency/provider IDs, and verify no duplicate grant. Re-disable payment intake if reconciliation diverges.

## Communication and review

Tell customers payment is awaiting confirmation, not failed or fulfilled. Review timeouts, signatures, idempotency, and provider incident chronology.
