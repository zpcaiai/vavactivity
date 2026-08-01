# Batch 8 implementation plan

Authority: the supplied Batch 8 counseling, scheduling, appointment, delivery,
record and follow-up specification.

1. Add multilingual mentors, counseling services and Catalog SKU mappings.
2. Generate IANA-timezone availability from recurring rules and overrides.
3. Protect final allocation with PostgreSQL locks, expiring slot holds and
   non-overlap constraints.
4. Encrypt versioned intake and implement idempotent request, review, proposal,
   confirmation and direct-booking flows.
5. Reserve and consume `counseling_credits` only through verified Entitlements;
   payment returns never confirm appointments.
6. Snapshot reschedule, cancellation and no-show policy and preserve histories.
7. Provide scoped, short-lived meeting access and protect private locations.
8. Separate client summaries, mentor notes, operations records and restricted
   safety referrals.
9. Build user and RBAC-gated administration journeys.
10. Verify unit, integration, DST, concurrency, security and browser workflows,
    then recursively run Batch 1-7 gates.

Scheduling mode, cancellation/refund, no-show credit consumption, recording,
transcription, retention and professional-scope approval remain undecided.
Development defaults to manual confirmation, no automatic refund, no automatic
no-show consumption, recording/transcription off and least-disclosing access.

## Evidence recorded 2026-07-31

- Alembic `20260731_0027` applied against PostgreSQL: 14 counseling tables and
  the `counseling_appointments_no_overlap` exclusion constraint are present.
- Seed is repeatable: 173 permissions, 18 roles, Catalog product/SKU/price,
  mentor, localized service and timezone availability.
- `make counseling-verify` passed every Batch 8 gate and all recursive Batch
  1-7 tests/E2E. Its final redundant image metadata lookup was blocked twice by
  registry `EOF`; the images had already built successfully immediately before.
- `VAV_VERIFY_REUSE_BUILT_IMAGES=true make verify` then passed 109 backend
  tests, 12 frontend tests, both production builds and OpenAPI freshness using
  those exact locally built images.
