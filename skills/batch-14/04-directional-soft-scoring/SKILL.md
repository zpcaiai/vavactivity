# Directional soft scoring

Score how well the target matches what the source explicitly asked for, using the member's own
importance levels and transparent platform defaults. `required` is a hard constraint and is
never double-counted as a soft weight. Missing information lowers confidence instead of
scoring zero, and confidence is the minimum of coverage and an absolute-information floor, so
one lucky matching field can never look like a confident perfect match. Every scoring function
returns basis points or `None`; scoring is pure and deterministic for identical inputs, and the
policy version travels with every score.
