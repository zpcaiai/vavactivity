# Recommendation testing and acceptance

Cover unit, integration, concurrency, security, fairness and end-to-end levels.
Correctness metrics — hard-constraint violations, eligibility violations, blocked
pair leakage, privacy leakage, contact leakage, unapproved profile exposure —
must be exactly zero and block a release when they are not. Concurrency proves
one canonical pair, one daily batch, budget limits under parallel reservation and
deduplicated feedback. Security proves blocked, suspended and unapproved profiles
never appear, that contact details and private preferences never leave the
backend, that members reach only their own batches, and that a moderation failure
fails closed. Fairness compares equally qualified populations and never justifies
pushing an unsuitable recommendation.
