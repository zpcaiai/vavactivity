# Safety block propagation failure

## Symptoms and impact

A blocked pair remains reachable through profile, recommendation, invitation, contact grant, messaging, or relationship journey paths.

## Detect

Treat any bypass as critical. Run the cross-path block matrix, inspect safety gateway decisions, pair exclusions, invalidation jobs, grants, and journey state.

## Immediate containment

Synchronously deny the pair at the central gate, freeze their shared artifacts, prioritize propagation, and protect reporter identity. Do not wait for eventual consistency to deny access.

## Recovery

Repair the propagation consumer/idempotency cursor, replay the block event, revoke grants/invitations, invalidate recommendations, and freeze journeys.

## Verification and rollback

Use both user directions across every path and admin redaction checks; bypass rate must be zero. Keep matching/interaction features constrained otherwise.

## Communication and review

Escalate to safety/privacy incident owners, communicate non-shaming support, and review all access paths, latency SLO, and red-team fixtures.
