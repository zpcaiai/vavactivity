# Bidirectional scoring

## Why not an average

A plain average hides the case that matters most:

```text
A → B = 9500
B → A = 2500
average = 6000   ← looks like a decent match, is not one
```

The composition therefore uses the weaker direction plus a geometric mean, and
suppresses strongly asymmetric pairs further:

```text
combined = 0.6 × sqrt(A→B × B→A) + 0.4 × min(A→B, B→A)
if |A→B − B→A| > 3000: combined ×= (1 − min(0.3, (gap − 3000) / 20000))
```

Both directions must also clear their own floors
(`RECOMMENDATION_MIN_DIRECTIONAL_SCORE_BPS`,
`RECOMMENDATION_MIN_BIDIRECTIONAL_SCORE_BPS`). These are engineering defaults
for a transparent baseline, not a claim about human compatibility, and they are
expected to move once real evaluation data exists.

## Directional score

```text
total = Σ(raw_match_bps × weight) ÷ Σ(weight where information exists)
```

- Weight comes from the member's stated importance: very important 100,
  important 70, nice to have 35, no preference 0.
- `required` is already enforced as a hard constraint and carries weight 0 —
  it is never counted twice.
- Missing information is omitted from both sums and lowers confidence instead of
  scoring zero.

## Confidence

```text
confidence = 0.5 × weight coverage + 0.3 × informed feature breadth + 0.2 × profile readiness
```

Breadth is capped at eight informed features, so one matching field cannot
produce a confident perfect score.

## What the member sees

Mutual strengths (both directions agreed), the conditions they themselves set
that matched, topics worth exploring, and information still missing. Never a
percentage, never the other member's score, never the other member's criteria.
