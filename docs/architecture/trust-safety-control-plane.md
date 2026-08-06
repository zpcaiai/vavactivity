# Trust & Safety control-plane invariants

1. A member block is immediate, bidirectional at every visibility/access boundary and independent
   from a report. Unblocking never reconstructs old recommendations, matches, invitations,
   relationships or contact grants.
2. Reports are reporter-scoped. User DTOs never contain descriptions, evidence, investigator
   identity, priority or the reporter identity of another person.
3. Evidence is minimized, encrypted and checksummed. Full AI conversations, counseling records,
   payment-card data and unrelated relationship history are not copied by default. Every sensitive
   evidence read records actor, purpose and access type.
4. Automated outputs can hold content, rate-limit, freeze an interaction or request review. They
   cannot make permanent high-impact findings. High-impact human actions use creator/approver
   separation and an append-only audit trail.
5. Restrictions compose by union. Lifting or expiring one restriction does not lift another.
   Membership, payment status and product tier never bypass a restriction.
6. Appeals are independent. An overturn creates remediation, preserves the original history and
   restores only still-valid platform access—not another user's choice or withdrawn consent.
7. Storage, cache or rule-evaluation failure returns `safety_unavailable` and denies the operation.
   The release remains blocked until block bypass and contact leakage are both zero.
