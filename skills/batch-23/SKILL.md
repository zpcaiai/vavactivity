---
name: vav-batch-23-information-architecture-user-journeys
description: Operate the governed VAV information architecture, navigation, task, journey, handoff, search, help, dead-end and experience-closure control plane.
---

# Goal

Run the complete Batch 23 experience loop without replacing domain truth or fabricating certification.

# Procedure

1. Read the six manifests under `config/experience/` and the policies under `docs/experience/`.
2. Run `make quality-verify` and `make ui-verify` when their required services are available.
3. Run the Batch 23 migration and seed; seeds may activate reference definitions but never certification.
4. Run every `experience-*` check in `make/batch-23.mk`.
5. Treat critical dead ends, broken notification links, stale task state, unauthorized search and sensitive handoff context as release blockers.
6. Register only measured, checksum-bound evidence. Keep external gates `NOT_RUN` and production `NOT_CERTIFIED` until independently accepted.

# Invariants

- Backend eligibility and domain modules are authoritative.
- Restricted users retain safety, privacy, appeal and account-security paths.
- Handoff and deep-link acceptance revalidates user, expiry, permission and target state.
- Search never exposes one-sided likes, private reflections, evidence or payment secrets.
- Experience closure cannot override quality, business, security or data failures.
