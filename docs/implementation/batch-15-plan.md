# Batch 15 Implementation Plan — Likes, Mutual Matches, Introductions and Contact Exchange

Batch 15 turns the recommendations Batch 14 delivers into expressed choice. It records what a
member decides about a specific recommendation item, detects when two members have chosen each
other, carries that into a formal introduction, and — only when both sides separately agree —
opens a scoped, revocable channel to verified contact details.

It does not own the relationship that follows, and it does not own safety enforcement.

## Module boundary

| Concern | Owner |
| --- | --- |
| Account, login, RBAC | Batch 2 identity |
| Activity participation and post-event mutual choice source events | Batch 6 activities |
| Verified contact points, consent records, erasure requests | Batch 12 privacy |
| Approved dating profile, projections, profile status | Batch 13 matchmaking_profiles |
| Recommendation items, candidate pairs, scores, exposure | Batch 14 recommendations |
| Like, skip, withdrawal, mutual match, invitation, contact exchange, interaction invalidation | **Batch 15 matchmaking_interactions** |
| Relationship journey, stages, pause, end, milestones | Batch 16 |
| Membership entitlements and quotas | Batch 17 |
| Reports, blocks, restrictions, investigations | Batch 18 |

Batch 15 reads recommendation items and profile status; it never recomputes a score, never
reads a preference document, and never reaches into another module's tables except through a
gateway that returns a decision.

## Structural deviation from the specification

The specification proposes a deep DDD tree (`api/`, `application/commands/`, `domain/entities/`,
`infrastructure/repositories/`). Every module actually in this repository — including Batch 14,
which is the largest — uses flat, purpose-named files under `modules/<name>/`. This batch
follows the repository, not the specification tree, because a single divergent module would make
the codebase harder to navigate and would not survive the Batch 26 admin-completeness audit.

The mapping is one-to-one and nothing is dropped:

| Specification | This repository |
| --- | --- |
| `api/like_router.py`, `skip_router.py`, `mutual_match_router.py`, `introduction_router.py`, `contact_exchange_router.py`, `interaction_history_router.py` | `router.py` |
| `api/admin_*.py` | `admin_router.py` |
| `domain/entities`, `value_objects`, `enums`, `state_machines` | `domain.py` |
| `domain/policies` | `policies.py` |
| `application/services/like_service.py`, `skip_service.py` | `likes.py` |
| `application/services/mutual_match_service.py`, `activity_match_bridge_service.py` | `matches.py` |
| `application/services/invitation_service.py`, `relationship_handoff_service.py` | `invitations.py` |
| `application/services/contact_exchange_service.py` | `contact_exchange.py` |
| `application/services/interaction_invalidation_service.py` | `invalidation.py` |
| `infrastructure/locking`, idempotency | `idempotency.py` |
| `integrations/*.py` | `gateways.py` |
| `application/dto` | `schemas.py` |
| `permissions.py` | `vav/modules/identity/permissions.py` (where every other module registers) |

## Delivery slices

1. **Canonical pair domain** — one unordered `(user_low_id, user_high_id)` row per pair, with a
   `CHECK (user_low_id < user_high_id)` and a unique constraint so reversing the arguments
   cannot create a second pair. Interaction history is append-only and stores status transitions
   with controlled metadata, never a full skip reason or a contact detail. Migrations `0060`
   and `0064`.
2. **Likes and skips** — directional records scoped to a valid recommendation item, with a
   partial unique index on `(actor, target) WHERE status IN ('active','matched')`, typed skips
   with cooldowns, encrypted free-text skip reasons, and withdrawal. Migrations `0060`–`0061`.
3. **Mutual-match detection** — pair-row lock, upsert of the current direction, reverse-like
   lookup, and a single mutual match guarded by `UNIQUE(pair_id)`. The database constraint is
   the final boundary; the application never relies on read-then-write alone. Migration `0061`.
4. **Activity bridge** — consume `activity.mutual_choice.created` through a deduplicating inbox,
   attach the activity as an additional source of the same match, and never let a check-in or a
   grouping become a choice. Migrations `0061`, `0064`.
5. **Introduction invitations** — one pending invitation per match enforced by a partial unique
   index, encrypted message body screened for contact information, TTL expiry, and mutually
   exclusive accept / decline / cancel / expire outcomes. Migration `0062`.
6. **Relationship handoff** — acceptance emits exactly one `matchmaking.relationship_handoff.created`
   event for Batch 16. This batch does not model a single relationship stage.
7. **Contact exchange** — request, two independent consents, and grants that exist only after
   both sides consent. Consent binds to a hash of the selected verified contact points, so a
   changed phone number suspends the grant instead of silently widening it. Reveal is a
   short-lived viewer-scoped token and every reveal writes a sensitive-access audit row.
   Migration `0063`.
8. **Idempotency and concurrency** — an `Idempotency-Key` on every member write, a stored
   request hash that rejects key reuse with a different body, optimistic versions on invitation
   transitions, and row locks on the pair. Migration `0064`.
9. **Invalidation** — profile pause, account suspension, erasure start, block, restriction and
   relationship start all invalidate interactions through one service, and display-time rechecks
   run even when a snapshot already exists.
10. **Events and feedback** — outbox events for every transition, notification policy that never
    reveals a one-sided like, and recommendation feedback carrying `recommendation_item_id`,
    `candidate_pair_id`, `strategy_version` and `batch_id` back to Batch 14.
11. **User web and admin web** — member journeys for like, skip, undo, matches, invitations and
    contact exchange; an administrator diagnostic centre that can freeze, invalidate, revoke and
    replay, but cannot manufacture a choice.
12. **Tests** — unit, integration, concurrency, security and privacy, covering every scenario in
    specification sections 31–38.

## Non-negotiables

- A one-sided like is invisible to its target. No notification, no API, no count, no ordering
  change, no admin list without a separate sensitive permission and a stated purpose.
- A skip is not a block and never becomes a hidden hard preference.
- Mutual like does not open contact details. The default policy is
  `mutual_confirmation_required` and automatic exchange stays off.
- Only verified contact points a member explicitly selected can ever be revealed.
- A block revokes grants and unused reveal tokens immediately, and the blocked side is told
  nothing about who reported what.
- Concurrent reciprocal likes produce exactly one mutual match and exactly one notification.
- An administrator cannot like, accept, decline or consent on a member's behalf, and cannot turn
  a decline into an acceptance.
- When moderation cannot be evaluated, the interaction fails closed.

## Open decisions

These are recorded in `docs/product/decision-register.md` and stay configurable rather than
hardcoded.

| Decision | Interim behaviour |
| --- | --- |
| `matchmaking_direct_profile_like` | Disabled. A like requires a valid recommendation item or an approved activity source. |
| `matchmaking_contact_exchange_policy` | `mutual_confirmation_required`. Automatic exchange after acceptance is implemented but off. |
| `matchmaking_invitation_expiry_policy` | 7-day TTL; an expired invitation returns the match to `active` and starts a 30-day cooldown. |
| `matchmaking_repeat_invitation_policy` | Resend allowed only after expiry plus cooldown. A decline does not permit an automatic resend. |
| `matchmaking_declined_pair_cooldown` | 180 days before the pair can be recommended again. |
| `matchmaking_contact_grant_ttl` | No automatic date expiry; grants end on withdrawal, block, restriction, contact change or relationship end. |
