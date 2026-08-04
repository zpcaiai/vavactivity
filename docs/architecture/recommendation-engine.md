# Recommendation Engine

The recommendation engine answers one question: *which people should these two see each other
as?* It is bidirectional by construction — A finding B suitable is not a recommendation until B
would also accept A.

## Inputs

The only profile input is the Batch 13 de-identified recommendation projection:

```
age_bucket, age_years, country_code, region_code, city_code, gender_code,
eligible_partner_gender_codes, faith_codes[], relationship_intent, marital_status_code,
children_status_code, relocation_willingness, language_codes[], lifestyle_codes[],
indexed_preference_criteria[], approved_profile_version, preference_version,
privacy_settings_version, projection_version, projection_checksum
```

Everything else — narratives, photos, contact details, payments, counseling notes, AI
conversations, the raw date of birth — is out of reach by design, not by convention.

## Pipeline

```
projection ─▶ pool entry ─▶ recall ─▶ safety gateway ─▶ hard constraints (both directions)
          ─▶ directional scores (A→B, B→A) ─▶ bidirectional combination ─▶ thresholds
          ─▶ adjustments ─▶ diversification (MMR) ─▶ exploration slots ─▶ batch items
          ─▶ explanations ─▶ exposure ─▶ feedback ─▶ bounded tuning
```

Each stage may only *remove* candidates or *reorder* them. No stage may admit a candidate that
an earlier stage rejected. Diversification raises `ValueError` if it is ever handed a policy
claiming otherwise.

## Versioned strategy

Every weight, threshold and policy lives in one `recommendation_strategies` row:

| Policy | What it fixes |
| --- | --- |
| `hard_constraint_policy` | the criteria allow-list, unknown handling, relaxable and never-relaxable sets |
| `feature_manifest` | 16 features, their projection field, scoring function, default weight, explainability and sensitivity |
| `scoring_policy` | importance weights, missingness policy, confidence floors |
| `bidirectional_policy` | combination function, minimum directional weight, imbalance penalty |
| `ranking_policy` | sort order, novelty, repeat and popularity adjustments |
| `diversification_policy` | MMR lambda, dimensions, per-city cap |
| `exposure_policy` | what counts as an exposure, cooldowns, what membership may and may not affect |
| `explanation_policy` | generation mode, section caps, caveat, forbidden disclosures |
| `cold_start_policy` | exploration slots, protection window, exploration limits |

A strategy cannot be activated without an approver and a passing evaluation — a trigger raises
if either is missing. Rollback re-activates a previous version rather than editing the live one.

## Bidirectional evaluation

`constraints.evaluate_pair` runs the viewer's criteria against the candidate *and* the
candidate's criteria against the viewer, plus a mutual relationship-eligibility check. It
returns `passed`, `blocking_codes`, `unknown_codes`, `relaxations_applied` and per-direction
detail with a `reason_code`.

Three rules make this safe:

1. Only a criterion on the approved allow-list may exclude. Anything else is reported as
   `criterion_not_approved_for_hard_filtering` and never blocks.
2. A blank field is unknown. The member's own `allow_unknown` decides whether an unknown
   excludes; the platform never guesses on their behalf.
3. Relaxation needs the viewer's opt-in *and* a relaxable criterion, and applies only to the
   viewer's own conditions. The other party's constraints are never relaxed for anyone.

## Scoring and confidence

Each feature returns basis points or `None`. `None` means "no basis to judge", which lowers
confidence instead of scoring zero:

```
total       = Σ(raw × weight) / Σ(weight over features that had data)
coverage    = effective_weight / declared_weight
absolute    = effective_weight / confidence_full_information_weight
confidence  = min(coverage, absolute)
```

The absolute term is why a profile with one matching field cannot present as a confident
perfect match: coverage would say 100%, but the absolute floor says otherwise.

`required` never appears in `IMPORTANCE_WEIGHTS`. It is a hard constraint, and re-counting it as
a soft weight would let one preference dominate twice.

## Combination

```
mean      = harmonic_mean(a, b)
combined  = (mean × (1 − w) + min(a, b) × w) / 1        # w = minimum_directional_weight_bps
combined -= (|a − b| ÷ 1000) × balance_penalty
```

Symmetric, floored by the weaker side, and penalised as the gap widens. A 95/25 split lands far
below the arithmetic 60 it would otherwise show.

## Explanations

Template-only, drawn from `STRENGTH_TEMPLATES`, `GAP_TEMPLATES` and `DIFFERENCE_TEMPLATES`.
`assert_safe()` runs before every explanation is persisted and raises if the payload contains a
criterion code, an importance weight, a directional score, a rank or a probability marker. The
member always sees the caveat: 推荐只是一个认识的机会，不代表平台对适配结果的保证。

## Exposure

A rendered card is not an exposure. `card_impression` never counts; `card_visible` counts only
past `RECOMMENDATION_EXPOSURE_VISIBLE_MIN_MS`; opening a profile or photo always counts.
Receiving and being shown are separate daily budgets, so a member whose own inbox is full may
still be shown to others — and a heavily shown profile is protected from further exposure
without losing any interaction it already has.

## Feedback

| Feedback | Cooldown | Removes pair | Learns |
| --- | --- | --- | --- |
| `viewed`, `impression` | no | no | no |
| `profile_opened`, `liked` | no | no | yes |
| `skipped`, `not_relevant` | yes | no | yes (clamped) |
| `introduction_declined` | yes | no | yes |
| `mutual_matched`, `introduction_accepted`, `relationship_started` | no | yes | yes |
| `reported`, `blocked` | no | yes | **never** |

Learned adjustments move by ±5 and clamp at ±40 against default weights of 15–90, so no amount
of feedback can turn a soft preference into an exclusion. `reason_details` is encrypted at rest
and never reaches the other member.

## Evaluation and release

`evaluation.run` computes correctness, ranking, coverage and fairness metrics and compares them
to `GUARDRAIL_THRESHOLDS`. Five guardrails have a ceiling of zero — hard-constraint violations,
eligibility violations, blocked-pair leakage, privacy violations and safety-restriction
violations. Any of them fails the run, records `recommendation.release.blocked`, and leaves the
previous strategy active. Click-through and dwell time are not guardrails and cannot pass a
release on their own.
