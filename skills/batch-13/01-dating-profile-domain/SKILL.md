# Dating profile domain

Model one dating profile per eligible member with a `profile_number`, a bound schema
release and the full `DatingProfileStatus` lifecycle. Age is derived by the backend from the
Batch 12 protected date of birth; the matchmaking domain never stores a second copy and never
trusts a client-supplied age. Profile versions are immutable once submitted and are enforced by
a database trigger, not only by application code.
