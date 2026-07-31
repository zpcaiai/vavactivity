# Batch 2 implementation plan

Authority: the supplied Batch 2 identity and access-control specification.

1. Add the identity, session, token, RBAC, invitation and append-only security-event schema.
2. Add Argon2id password policy, Ed25519 access tokens, opaque rotating refresh tokens and audience isolation.
3. Add registration, verification, login, recovery, account and device-session APIs.
4. Seed permissions and roles; add administrator bootstrap, invitation and governance APIs.
5. Build user and administrator authentication screens with in-memory access tokens.
6. Verify unit, integration and security invariants before running the Batch 1 regression.

Unresolved production identity-provider, MFA and phone-verification choices remain disabled extension points.
