# Bidirectional hard constraints

A recommendation requires both people to qualify for each other. Relationship eligibility is
checked in both directions and is never relaxed. Only criteria on the approved
`HARD_CONSTRAINT_CRITERIA` allow-list may exclude anyone, whatever a member or an operator
asks for; everything else stays a soft signal. A blank field is unknown, not a failure — the
member decides via `allow_unknown` whether unknowns are acceptable. Relaxation requires the
viewer's own opt-in *and* a relaxable criterion, applies only to the viewer's own conditions,
and is disclosed on the resulting card. The other party's constraints are never relaxed for
anybody. Diagnostics are aggregate only: they report how many candidates a criterion excluded,
never who.
