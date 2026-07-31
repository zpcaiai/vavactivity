---
name: vav-rbac-permission-engine
description: Implement deny-by-default roles, permissions and grants.
---

Seed stable permission codes and default roles idempotently. Evaluate active,
unexpired grants in the backend, include RBAC version invalidation and require a
reason plus audit event for grants and revocations.
