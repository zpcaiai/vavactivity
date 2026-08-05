# Matchmaking Interaction State Machines

Five state machines carry a member from a recommendation card to a mutually agreed contact
exchange. They are deliberately separate: expressing interest, being formally invited, and
agreeing to be contactable are three different consents, and collapsing them would let one click
imply the other two.

## Canonical pair

Every two-person state lives under one `matchmaking_pairs` row keyed by
`(user_low_id, user_high_id)` where `user_low_id < user_high_id`, enforced by a `CHECK` and a
unique constraint. Reversing the argument order cannot create a second pair, so "A and B" is one
row no matter who acts first.

```
pending ──first interaction──▶ interacting ──reciprocal like──▶ mutual_matched
   │                                │                                 │
   │                                └────────── block / restriction ──┤
   └──────────────────────────────────────────────────────────────────▼
                                                                  restricted
```

`restriction_version` increments on every safety or privacy change and is part of every cache
key, so a stale cached view cannot outlive a block.

## Like

```
        ┌──────────── withdraw (before match) ─────────────┐
        ▼                                                  │
   ACTIVE ──reverse active like──▶ MATCHED            WITHDRAWN
        │                              │
        │                              └── match closed ──▶ (stays MATCHED; history is not rewritten)
        ├── profile paused / block / erasure ──▶ INVALIDATED
        └── TTL reached ──▶ EXPIRED
```

- A like requires a recommendation item that belongs to the actor, is unexpired, and passed a
  fresh eligibility recheck.
- `UNIQUE(actor, target) WHERE status IN ('active','matched')` makes a duplicate click a
  database-level impossibility, not a race the application hopes to win.
- A matched like cannot be deleted. Withdrawal after a match is a match-lifecycle operation:
  before an invitation it closes the match, with a pending invitation it cancels the invitation
  and closes the match, and after acceptance it belongs to Batch 16's end-of-relationship flow.
- Withdrawal before a match is silent — the target never learned about the like in the first
  place, so there is nothing to retract.

## Skip

```
   ACTIVE ──undo window──▶ WITHDRAWN
        │
        ├── cooldown elapsed ──▶ EXPIRED
        └── later like on same pair ──▶ SUPERSEDED
```

`not_now` starts a short cooldown, `not_interested` a long one. Neither is a block: a skip does
not stop the other member from being recommended to anyone else, does not notify them, and never
becomes an implicit hard constraint. Free-text reasons are encrypted at rest and are visible
only to their author and the recommendation engine.

## Mutual match

```
                     ┌── invitation sent ──▶ INVITATION_PENDING ── accepted ──▶ INTRODUCTION_ACCEPTED
                     │                              │                                    │
   ACTIVE ───────────┤                              ├── declined / cancelled ──▶ CLOSED   └── Batch 16 owns what follows
                     │                              └── expired ──▶ ACTIVE or CLOSED (policy)
                     ├── either member closes ──▶ CLOSED
                     ├── profile / privacy / erasure ──▶ INVALIDATED
                     └── block / restriction ──▶ SAFETY_FROZEN
```

Creation is the only genuinely contended path. The transaction is:

```
canonical_pair(a, b)
  → INSERT ... ON CONFLICT DO NOTHING on matchmaking_pairs
  → SELECT the pair row FOR UPDATE
  → upsert this direction's like
  → look up the reverse active like
  → if absent: commit (one-sided, silent)
  → if present: create the mutual match, flip both likes to MATCHED,
                move the pair to mutual_matched, write one outbox event
  → commit
```

Two members clicking simultaneously contend on the same pair row, so one transaction creates the
match and the other observes it. `UNIQUE(pair_id)` on `matchmaking_mutual_matches` is the final
guarantee, and the single outbox row is what makes the notification exactly-once rather than
twice.

Before a match is created, both sides are rechecked: accounts active, profiles active, no block,
no restriction, no erasure in progress, no relationship already running. A failed recheck
invalidates the like that triggered it and tells the other side nothing.

## Introduction invitation

```
   PENDING ── recipient accepts ──▶ ACCEPTED ──▶ one relationship_handoff event
        ├── recipient declines ──▶ DECLINED  (reason stays private)
        ├── sender cancels ─────▶ CANCELLED
        ├── TTL reached ────────▶ EXPIRED    (expiry worker and accept race to one outcome)
        └── block / profile / privacy ──▶ INVALIDATED
```

`UNIQUE(mutual_match_id) WHERE status = 'pending'` allows at most one open invitation per match.
Accept carries `expected_invitation_version`; a stale version fails with
`INVITATION_STATE_CHANGED` rather than resurrecting a cancelled invitation.

The sender sees only "the other member did not continue with this introduction." The decline
reason code is stored for safety review and never returned to the sender.

Message bodies are encrypted and screened: phone numbers, email addresses, messaging handles,
external links, payment requests and investment solicitations are rejected, because the contact
exchange flow exists precisely so that contact details are not smuggled through free text.

## Contact exchange

```
   NOT_REQUESTED ──request──▶ REQUESTED ──one consent──▶ ONE_SIDE_CONSENTED
                                                              │
                                              second consent  ▼
                                                     MUTUALLY_CONSENTED
                                                              │
                                        hash + safety recheck ▼
                                                          ACTIVE
                                                              │
                        one side withdraws / contact changed  ├──▶ PARTIALLY_REVOKED
                        both withdraw                          ├──▶ REVOKED
                        block / restriction / erasure          └──▶ INVALIDATED
```

Preconditions for `ACTIVE`: the introduction is accepted, both members consented independently,
each selected at least one **verified** contact point, no block or restriction exists, and the
stored hash of each selected contact point still matches its current value.

The hash is what makes consent specific rather than open-ended. A member consents to sharing
*this* verified number; replacing the number breaks the hash, suspends the grant, and requires a
fresh confirmation. A new value is never folded into an old consent.

Reading a contact detail is two steps: the list endpoint returns masked values, and a separate
reveal call issues a short-lived token bound to the viewer. Every reveal writes a sensitive
access audit row. Withdrawal invalidates unused tokens immediately.

The platform revokes access; it does not claim to erase what the other member already wrote
down. The interface says so plainly rather than implying a guarantee that cannot be kept.

## Invalidation fan-in

One service handles every external signal so that the rules cannot drift apart:

| Source event | Effect |
| --- | --- |
| `dating_profile.paused` / `.suspended` / `.archived` | no new likes or invitations; open recommendation items invalidated; accepted introductions handed to Batch 16 |
| `dating_profile.privacy_updated` | display rechecks fail; cached views invalidated |
| `user.account.suspended` | all open interactions invalidated |
| `privacy.erasure.started` | no new interactions; pending invitations withdrawn; unstarted matches closed; grants revoked |
| `moderation.block.created` | unmatched likes invalidated, match frozen, pending invitation invalidated, grants and reveal tokens revoked, notifications stopped |
| `moderation.restriction.created` / `report.high_risk` | pair frozen pending review |
| `relationship.journey.started` | pair excluded from further recommendation |
| `relationship.journey.closed` | Batch 16 decides whether the pair returns to the pool |

Invalidation never physically deletes history. A row moves to an invalidated status and the
transition is appended to `matchmaking_interaction_history`, because a safety investigation that
cannot reconstruct what happened is not an investigation.

## What the member sees when something is invalidated

The member-facing state is deliberately thin: "this introduction is no longer available." Not
who blocked whom, not that a report exists, not which rule fired. Internal reason codes stay in
the audit trail and behind the sensitive-read permission.
