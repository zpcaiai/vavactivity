---
name: vav-batch-02-identity-auth-rbac
description: Implement VAV account authentication, verified email, EdDSA JWTs, rotating refresh sessions, RBAC, administrator governance and security audit.
---

# Goal

Deliver backend-authoritative identity and access control for the user and
administration applications.

# Required order

1. Read `project-manifest.yaml` and `docs/implementation/batch-02-plan.md`.
2. Run `make verify`.
3. Implement the skills in this directory in numeric order.
4. Keep access tokens in memory and refresh tokens in protected cookies.
5. Enforce audience isolation, CSRF, refresh-family reuse detection and RBAC server-side.
6. Record security-sensitive changes in append-only audit events.
7. Finish with `make auth-verify`.

# Invariants

- Passwords use Argon2id and reset or change revokes existing sessions.
- Email verification and recovery tokens are single-use, expiring and hash-only.
- Access JWTs use EdDSA, `kid`, issuer, audience and version claims.
- Refresh rotation is atomic; reuse revokes the entire token family.
- Frontend route guards never replace backend authorization.
- Production secrets are never seeded, logged or committed.
