# Batch 6 implementation plan

Authority: the supplied Batch 6 activity publication, registration, attendance,
grouping and post-event mutual-choice specification.

1. Add the activity aggregate, localizations, private locations, sessions and
   ticket links without duplicating Catalog price or inventory state.
2. Enforce reviewed publication, registration windows and explicit lifecycle
   histories.
3. Implement free, paid and approval-first registrations with versioned forms,
   Commerce order references and idempotent entitlement projection.
4. Implement deterministic waitlists and single-seat promotion under database
   locks.
5. Add privacy-safe, signed check-in passes and append-only attendance events.
6. Add reproducible grouping with locked plans and move history.
7. Add consented participant projections, confidential one-sided choices and
   unique reciprocal matches without contact disclosure.
8. Build public/user and permission-gated administration journeys.
9. Verify unit, integration, concurrency, security and browser workflows before
   the complete Batch 1–5 regression.

Activity eligibility, participant visibility, cancellation/refund handling and
contact exchange remain policy decisions. The technical defaults are
least-disclosing, require explicit reasons for high-risk operations and never
allow an administrator to choose on a user's behalf.

## Implemented evidence

Verified locally on 2026-07-31. Detailed results are recorded in
`docs/acceptance/batch-06-report.md`.

- Alembic revisions `0017`–`0021` define the activity, registration, waitlist,
  check-in, grouping and private mutual-choice records.
- The FastAPI activity module exposes public discovery, user registration and
  access, consented participant profiles, private choices, and RBAC-gated
  operator workflows.
- Free admission is verified through a zero-value Commerce order and active
  entitlement; paid admission remains webhook-authoritative.
- Celery advances lifecycle windows and manages waitlist offers.
- Vue user and operator journeys are available at `/activities`,
  `/account/activity-registrations` and `/admin/activities`.
- Unit, integration, concurrency, security and both browser acceptance journeys
  pass against the containerized stack.
- The 12 child Skills pass `quick_validate.py`; the root Skill is the Batch 6
  orchestrator and includes prompt evaluations.
