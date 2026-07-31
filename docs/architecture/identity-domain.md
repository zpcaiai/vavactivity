# Identity domain

VAV uses one `users` aggregate for members and administrators. Administrator access is
granted through time-bounded role assignments; it is not represented by a second password
store. Passwords use Argon2id. Verification, recovery and refresh credentials are persisted
only as one-way hashes.

Access tokens are short-lived Ed25519 JWTs. User and administrator audiences are isolated.
Opaque refresh tokens rotate exactly once under a row lock. Reuse of a replaced token revokes
the complete token family and increments `auth_version`.

Authorization is recalculated from active database role grants. Both `auth_version` and
`rbac_version` are compared with access-token claims on every authenticated request.
