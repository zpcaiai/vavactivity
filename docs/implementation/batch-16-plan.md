# Batch 16 Implementation Plan — Consent-Preserving Relationship Journeys

Batch 16 owns the durable journey after a Batch 15 introduction is accepted. It records shared
stage state, pauses, endings, milestones and optional reflection tools without turning a
relationship into a score or allowing an administrator, reminder, or AI system to make a
participant's decision.

## Boundaries

| Concern | Owner |
| --- | --- |
| Invitation and contact grants | Batch 15 `matchmaking_interactions` |
| Consent, encryption and AI relationship-context permission | Batch 12 `privacy` |
| Journey, stage proposal, pause/resume, ending, milestones, check-ins | **Batch 16 `relationships`** |
| Reports, blocks and investigations | Batch 18 moderation |
| Delivery of neutral reminders | Batch 11 notifications |

The repository uses flat purpose-named modules, so the specification's nested command/domain/
repository files map to `domain.py`, `service.py`, `schemas.py`, `router.py` and
`admin_router.py`, consistent with Batches 13–15.

## Delivery order

1. Migrations `0065`–`0070`: journey/participants/history/inbox, stage registry/proposals,
   pause/end, milestones, check-ins/reflections/action items, reminders/audit/dead letters.
2. Materialise `matchmaking.relationship_handoff.created` in the same transaction as invitation
   acceptance and keep replay idempotent by unique handoff and inbox keys.
3. Require the recipient to accept a stage proposal before shared state changes. One pending
   proposal per journey and row locks protect competing decisions.
4. Pause immediately at either participant's request. Resume only after the other participant
   accepts. Never schedule automatic resume.
5. End immediately after explicit confirmation by either participant; invalidate proposals and
   pauses, cancel reminders, revoke contact grants, close the match and start pair cooldown.
6. Encrypt private messages, milestone descriptions, check-in answers and reflections. A
   reflection is never processed by AI without an active Batch 12 consent plus the
   relationship-context preference.
7. Member and redacted operations interfaces, then unit/integration/concurrency/security/privacy
   and browser acceptance.

## Invariants

- `user_low_id < user_high_id` and one journey per accepted handoff.
- Formal stage changes, including `relationship_confirmed`, require both participants.
- Admin routes cannot accept/cancel a member proposal, confirm a stage, accept resume, or restore
  an ended journey.
- Pause/end are not engagement failures and never require the other participant's permission.
- Private reflections and private milestones are owner-only. Process history contains controlled
  codes, never private text.
- There is no relationship-health score, success rate, pressure reminder or inferred stage.
- Moderation uncertainty fails closed; safety freeze blocks progress and reminders.

## Verification

`make relationship-verify` is the Batch gate. It includes migration/seed, unit/integration,
concurrency, security/privacy and both browser suites. Earlier Batch 12–15 gates remain release
dependencies. Production deployment and external notification/customer certification remain
separate evidence gates.
