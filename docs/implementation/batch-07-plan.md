# Batch 7 implementation plan

Authority: the supplied Batch 7 course catalog, curriculum, learning, exercise
and certificate specification.

1. Add versioned multilingual courses, instructors, modules, lessons,
   prerequisites and completion policies.
2. Link course and bundle SKUs to curriculum without copying Catalog prices,
   promotions or inventory.
3. Project active `course_access` entitlements into version-pinned enrollments;
   use the same enrollment access decision for free and paid learning.
4. Provide provider-neutral, short-lived video playback authorization with
   scoped sessions and monotonic heartbeat evidence.
5. Preserve monotonic multi-device progress through idempotent learning events.
6. Add deterministic automatic grading, private learner responses, manual
   grading and attempt limits.
7. Recalculate completion on the backend and issue one minimal, revocable,
   publicly verifiable certificate.
8. Build public/user and RBAC-gated administration journeys.
9. Verify migrations, unit, integration, concurrency, security and browser
   workflows before recursively running the Batch 1–6 gates.

Video hosting, downloads, certificate name visibility, course expiry and
membership access remain product or legal decisions. Development uses a local
signed fake video adapter; production hosting is not inferred.

Verified locally on 2026-07-31. Detailed evidence is recorded in
`docs/acceptance/batch-07-report.md`.
