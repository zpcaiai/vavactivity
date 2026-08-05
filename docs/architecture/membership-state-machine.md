# Membership State and Authority Model

## Authority chain

```text
Catalog SKU -> Commerce Subscription -> MEMBERSHIP_ACCESS Entitlement
                                      -> Membership account/version/cycle
                                      -> Benefit grant -> optional quota bucket/ledger
                                      -> owning-module eligibility and safety checks
```

An event is a trigger, not authority. Projection reloads source rows and remains `pending` until
both Subscription and Entitlement are active. An inactive or expired Entitlement always denies
paid membership access.

## Account transitions

```text
pending -> active | trialing | cancelled | revoked
active -> past_due | paused | cancel_scheduled | expired | revoked
past_due -> grace_period | active | expired | revoked
grace_period -> active | expired | revoked
cancel_scheduled -> active | cancelled | expired
```

Cancelled, expired and revoked accounts are terminal history. Expiry closes paid grants and
quota buckets; the independent free account becomes effective without deleting user data or
separately purchased Entitlements.

## Quota invariant

```text
remaining = allocated + rollover - consumed - reserved >= 0
```

Reservation locks the selected bucket and uses the same inequality as a database update
predicate. Each reserve/consume/release operation has an idempotency key and immutable ledger
snapshot. An adjustment changes allocation through its own approved record; it never rewrites
consumption history.
