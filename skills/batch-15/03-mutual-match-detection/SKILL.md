---
name: vav-batch-15-mutual-match-detection
description: Create exactly one mutual match from two valid reciprocal choices.
---

# Rules

- Lock the canonical pair before inspecting the reverse like.
- Recheck both members before creating the match.
- Enforce one mutual-match row per pair in PostgreSQL.
- Mark both directional likes matched atomically.
- Emit exactly one mutual notification event with both recipients.

# Verify

Run a real two-session reciprocal race and assert one match and one notification.
