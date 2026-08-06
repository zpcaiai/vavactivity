# Data corruption

## Symptoms and impact

Checksums, invariants, ledger/recommendation relations, or object/database references disagree.

## Detect

Stop automated repair and compare authoritative records, audit/outbox history, backup manifests, replicas, and recent migrations/jobs.

## Immediate containment

Quarantine affected writes and jobs, preserve source copies, restrict sensitive access, and establish an incident/data owner.

## Recovery

Define the affected key/time range, restore into isolation, reconcile with append-only evidence, and apply reviewed idempotent repair—not direct ad hoc edits.

## Verification and rollback

Run domain invariants, cross-user isolation, financial/safety/privacy checks, and complete smoke before traffic. Re-quarantine on unexplained difference.

## Communication and review

State known/unknown data impact and notification obligations. Document cause, repair script, peer approval, and prevention.
