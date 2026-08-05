---
name: vav-batch-16-pause-resume-workflow
description: Implement immediate unilateral pause and mutually confirmed resume without timers.
---

# Rules

- A participant pause is effective immediately and invalidates pending stage proposals/reminders.
- Either participant may request resume; the requester cannot accept their own request.
- Decline keeps the journey paused. Never auto-resume or penalize a pause.
- Ending wins over a simultaneous resume and leaves no active pause.

# Verify

Test participant ownership, duplicate pause, self-accept denial, decline, accept and resume/end races.
