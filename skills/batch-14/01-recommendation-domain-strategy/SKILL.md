# Recommendation domain and versioned strategy

Model every weight, threshold and policy in one versioned `recommendation_strategies` record
rather than scattering them across services. A strategy may only go live once it has an
approver and a passing offline evaluation; the database enforces both with a trigger, and a
partial unique index guarantees exactly one active strategy per code. Batch and item
lifecycles are explicit state machines, and a candidate pair has exactly one row whatever
order the two members arrived in (`normalise_pair`). Prohibited signals — appearance, face,
ethnicity, income, spend, counselling records, AI conversation content, spiritual or mental
health inference — are declared in the domain and rejected at the scorer, not merely omitted.
