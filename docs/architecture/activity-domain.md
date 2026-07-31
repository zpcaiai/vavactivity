# Activity domain and authority boundaries

Batch 6 adds a first-phase activity delivery aggregate without moving ownership
of adjacent business facts.

## Authority map

| Fact | Authoritative module |
| --- | --- |
| Activity copy, schedule, registration policy | Activities |
| Ticket product, SKU, price and price availability | Catalog |
| Capacity, reservations and sold quantity | Catalog Inventory |
| Cart, order, payment, refund and reconciliation | Commerce |
| Admission right | Entitlements |
| Registration and approval projection | Activities |
| Check-in and group assignment | Activities |
| One-sided post-event choice | Activities, private |
| Moderation/block restriction | Trust boundary, projected locally until Batch 18 |

An activity ticket stores Catalog product and SKU identifiers. It does not copy
price, currency, discount or sold-capacity fields. A registration stores order,
quote and entitlement identifiers as projections. Only an active
`activity_admission` entitlement can confirm a paid registration; a browser
return URL cannot.

## Registration paths

Automatic registrations create an isolated one-item Commerce cart and order.
Explicit zero-price tickets use the same quote, reservation, order and
entitlement pipeline before becoming `confirmed`. Manual review can happen
before payment or after payment according to the snapshotted activity policy.
Full capacity creates a deterministic waitlist row, and a short-lived offer must
be accepted before checkout.

## Privacy and safety

Full addresses, online join URLs, form answers and review notes are encrypted.
Public DTOs expose only configured coarse location data. Check-in QR payloads
contain a random public reference, expiry and HMAC signature, never user PII.
Participant cards require explicit consent. One-sided choices have no ordinary
read or administration endpoint, reciprocal matches pass the interaction
restriction boundary, and match events state `contact_disclosed=false`.

## Operational jobs

The worker advances registration/activity time windows, expires stale waitlist
offers and creates ordered waitlist offers. Database row locks and unique
constraints protect checkout, active group membership, one choice per pair and
one reciprocal match per activity.

