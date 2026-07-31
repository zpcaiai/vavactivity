---
name: vav-identity-domain-model
description: Build the VAV users, sessions, tokens, roles, permissions, invitations and audit schema.
---

Create migrations `0002` through `0005`, ORM models and documented state machines.
Use UUIDs, CITEXT email uniqueness, explicit statuses, version fields and append-only
security events. Verify upgrade, downgrade ordering and database constraints.
