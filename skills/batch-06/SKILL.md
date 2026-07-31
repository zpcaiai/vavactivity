---
name: vav-batch-06-activities-registration-operations
description: Implement or review VAV activity publication, Catalog-linked tickets, registration and approval, waitlists, payment and entitlement projection, secure check-in, grouping, and private post-event mutual choice. Use this skill whenever work touches VAV activities or participant operations.
---

# Goal

Build the activity lifecycle while keeping Catalog authoritative for price and
capacity, Commerce authoritative for payment, and Entitlements authoritative for
admission.

## Required reading

1. Read `project-manifest.yaml`, the decision register and the Batch 6 plan.
2. Read every child `SKILL.md` in this directory.
3. Inspect Catalog, Commerce, Entitlement, RBAC, audit and outbox contracts.
4. Preserve unresolved policy as configuration with least-disclosing defaults.

## Execution order

1. Domain, publication, schedules and ticket links.
2. Registration, approval, projection and waitlist.
3. Check-in, grouping and post-event mutual choice.
4. User and administration journeys.
5. Unit, integration, concurrency, security and browser acceptance.

## Invariants

- Never duplicate price, discount, payment or sold-capacity state.
- Never let a browser payment return confirm a paid registration.
- Deduplicate every external projection.
- Keep private addresses, meeting links, form responses and internal notes out
  of public DTOs.
- Keep one-sided choices confidential across user, notification, cache, log and
  ordinary administration surfaces.
- Never disclose contact details automatically after a mutual choice.
- Lock capacity, waitlist promotions and reciprocal matching transactions.

## Verification

Run `make activity-verify`, then `make commerce-verify`.
