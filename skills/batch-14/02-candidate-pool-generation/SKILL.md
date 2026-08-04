# Candidate pool and candidate generation

The pool is built only from Batch 13's de-identified recommendation projection: coarse codes,
buckets and versions, never narratives, photos, contact details or a second copy of the date
of birth. A member leaves the pool the moment their account, profile, privacy or pause state
says so, and the entry carries the reasons so operations can explain it. Candidate generation
recalls on normalised codes, asks the moderation gateway about every pair (failing closed if
moderation is unavailable), evaluates hard constraints in both directions, and only then
scores. Each stored pair snapshots the projection and preference versions it was computed
from, so a stale candidate can be recognised and invalidated rather than silently reused.
