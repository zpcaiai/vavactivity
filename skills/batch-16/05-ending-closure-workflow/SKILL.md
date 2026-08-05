---
name: vav-batch-16-ending-closure-workflow
description: End a journey unilaterally after explicit confirmation and close downstream access.
---

# Rules

- The other participant's approval is never required; an explicit confirmation click is.
- Atomically invalidate proposals/pauses, cancel reminders, revoke contact grants, close the match
  and apply pair cooldown.
- Encrypt private/visible text and exclude it from events and routine operations views.
- Only a named safety permission may perform a safety ending; no restoration endpoint exists.

# Verify

Test end from active/paused/frozen, downstream revocation, repeat rejection and end/accept races.
