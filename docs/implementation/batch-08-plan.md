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
