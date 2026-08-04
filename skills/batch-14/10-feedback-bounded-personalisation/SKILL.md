# Feedback and bounded personalisation

Safety feedback (report, block) is routed to the safety domain and removes the pair from
candidacy; it is never recycled as taste data. A skip starts a cooldown, not a permanent
rejection. "Not relevant" may nudge one feature weight by a small clamped step and can never
create a new hard constraint. Free-text reasons are encrypted and never shown to the other
member. Every feedback write is idempotent. A member can switch personalisation off entirely
and reset every learned adjustment. The first release learns by reviewed rules and offline
re-estimation, not by an online model that rewrites user-facing logic.
