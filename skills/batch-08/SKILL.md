---
name: vav-batch-08-counseling-appointments-followup
description: Implement VAV mentors, counseling services, availability, appointments, credits, private records, follow-up and administration.
---

# Goal

Deliver the complete counseling lifecycle while preserving Catalog, Commerce,
Entitlement, privacy, RBAC, audit and Outbox authority boundaries.

## Required reading

1. Read the manifest, decision register and Batch 8 implementation plan.
2. Read every child `SKILL.md` in this directory.
3. Inspect Catalog counseling SKUs and Commerce counseling-credit behavior.
4. Keep scheduling, cancellation, no-show, recording and retention policy fail closed.

## Execution order

1. Domain, mentors, services and publication.
2. Timezone-safe availability, overrides and atomic slot holds.
3. Appointment review, proposals, Commerce and credit projection.
4. Reschedule, cancellation, meeting, delivery, records and follow-up.
5. User/admin journeys and all verification layers.

## Invariants

- Visible availability never confirms a booking; recheck and lock server-side.
- Payment never proves delivery and browser returns never confirm appointments.
- Credits reserve once and consume only after explicit delivery/no-show policy.
- Public, client, mentor-private, operational and safety records remain separate.
- Meeting URLs and private locations are short lived and principal scoped.
- Recording and transcription remain disabled without separate consent.
- Counseling is not psychotherapy, diagnosis, emergency response or legal advice.

## Verification

Run `make counseling-verify`; it must recurse through `make course-verify`.
