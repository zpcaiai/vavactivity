---
name: vav-activity-domain-model
description: Model VAV activities, localizations, private locations, sessions, ticket links, registrations, waitlists, attendance, grouping and post-event choices. Use whenever changing activity persistence or lifecycle contracts.
---

# Workflow

1. Keep activity operational data separate from Catalog and Commerce state.
2. Use explicit enums, histories, uniqueness constraints and timestamps.
3. Encrypt or redact private locations, meeting links, form answers and notes.
4. Add forward and rollback migrations and import every model in metadata.
5. Test constraints and state transitions.
