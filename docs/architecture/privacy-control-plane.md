# Privacy Control Plane

```text
User/Admin API
  -> ownership, reauthentication, purpose and RBAC checks
  -> privacy request / consent / visibility state machines
  -> module provider registry
       -> Identity
       -> Commerce
       -> Activities
       -> Courses
       -> Counseling
       -> AI
       -> Notifications
  -> encrypted export / erasure / retention workers
  -> redacted audit and user-visible status
```

Business modules remain sources of truth. Providers return stable inventory, export and
erasure-plan results. Unsupported operations are explicit and cannot silently succeed.
Restricted values are encrypted in the application, searchable contact values use keyed
HMAC, and unauthorized DTOs omit fields before serialization.
