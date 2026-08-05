# Relationship Journey State Machines

## Journey

```text
PENDING_ACTIVATION -> ACTIVE -> PAUSED -> ACTIVE
                         |         |
                         |         +---- participant ends ----+
                         +-- safety freeze -> SAFETY_FROZEN    |
                         +-- participant/safety ends ----------v
                                                        ENDED -> ARCHIVED
```

Pause and ending are unilateral safety valves. Resume is a new mutual decision and never occurs
from a timer. An ended journey has no restoration transition.

## Stage proposal

```text
PENDING -> ACCEPTED  (recipient only; atomically changes journey stage)
   |----> DECLINED   (recipient only; shared stage unchanged)
   |----> CANCELLED  (proposer only)
   |----> EXPIRED
   +----> INVALIDATED (pause, ending, safety or stale from-stage)
```

The proposal stores its `from_stage_code`; acceptance locks both proposal and journey and refuses
a stale proposal if the journey moved. A partial unique index permits one pending proposal per
journey. `relationship_confirmed` follows exactly the same mutual path.

## Pause and resume

```text
ACTIVE -- either participant --> PAUSED/ACTIVE_PAUSE
ACTIVE_PAUSE -- one requests --> RESUME_REQUESTED
RESUME_REQUESTED -- other accepts --> RESUMED + journey ACTIVE
RESUME_REQUESTED -- other declines --> ACTIVE_PAUSE + journey PAUSED
ACTIVE_PAUSE/RESUME_REQUESTED -- either ends --> ENDED
```

The requester cannot accept their own resume. Decline creates no automatic retry and exposes no
private reason.

## Ending cascade

An explicitly confirmed member ending, or an authorised Batch 18 safety ending, locks the journey
and atomically records the ending, invalidates pending stage proposals, closes active pause state,
cancels reminders, revokes Batch 15 contact grants, closes the mutual match, adds pair cooldown,
writes safe history and publishes an outbox event. Private text is encrypted and excluded from
history and event payloads.

## Privacy projection

Members see shared stage/history, shared milestones and their own private records. Routine
operators see pseudonymous participants and process status only. Sensitive reads require a
separate permission/purpose and audit trail. No projection computes a health or success score.
