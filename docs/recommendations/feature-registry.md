# Recommendation feature registry

Version `1.0.0`. Every feature is declared in
`services/api/src/vav/modules/recommendations/features.py`; nothing outside this
registry can influence a score, which is what makes the prohibited signals
structurally impossible rather than merely discouraged.

| Feature | Group | Function | Criterion | Default weight | Sensitivity |
| --- | --- | --- | --- | --- | --- |
| `faith_status_alignment` | faith_and_values | set overlap | `faith_status_code` | 70 | restricted |
| `church_tradition_overlap` | faith_and_values | set overlap | `church_tradition_codes` | 50 | restricted |
| `marriage_faith_importance_alignment` | faith_and_values | ordered distance | `marriage_faith_importance` | 60 | restricted |
| `location_compatibility` | location_and_relocation | geographic | — | 70 | confidential |
| `relocation_alignment` | location_and_relocation | exact match | `relocation_willingness` | 35 | confidential |
| `relationship_intent_alignment` | relationship_intent | exact match | `relationship_intent` | 90 | controlled public |
| `age_preference_centrality` | relationship_intent | range match | `age_range` | 40 | controlled public |
| `marital_status_alignment` | family_and_parenting | exact match | `marital_status_code` | 50 | restricted |
| `children_expectation_alignment` | family_and_parenting | exact match | `open_to_partner_with_children` | 60 | restricted |
| `desire_children_alignment` | family_and_parenting | exact match | `desire_children_code` | 70 | restricted |
| `daily_schedule_alignment` | lifestyle | exact match | `daily_schedule_code` | 30 | confidential |
| `smoking_alignment` | lifestyle | exact match | `smoking_status_code` | 40 | confidential |
| `alcohol_alignment` | lifestyle | exact match | `alcohol_use_code` | 30 | confidential |
| `interest_overlap` | interests | jaccard | `leisure_interest_codes` | 35 | controlled public |
| `communication_style_overlap` | communication | set overlap | `communication_preference_codes` | 40 | confidential |
| `language_overlap` | language | set overlap | `language_codes` | 60 | controlled public |
| `education_alignment` | education_and_work | exact match | `education_level_code` | 25 | confidential |
| `profile_readiness` | profile_readiness | readiness | — | 0 (confidence only) | controlled public |

`profile_readiness` affects display confidence and ranking stability only. It is
never a judgement of a person.

## Permanently prohibited signals

Photo attractiveness, facial features, skin tone, ethnicity inference, income
inference, social class inference, health inference, personality diagnosis,
spiritual maturity scoring, mental health status, AI conversation content,
counselling records, payment capacity and spend amount. `assert_registry_is_clean()`
fails closed if any of them ever appears in the registry, and operators cannot
add features through the admin surface.

## Scoring functions

| Function | Behaviour |
| --- | --- |
| `exact_match` | 10000 on equality or membership, else 0 |
| `set_overlap` | shared ÷ smaller set, so a member with two interests is comparable to one with twenty |
| `jaccard` | shared ÷ union |
| `ordered_distance` | linear decay over the declared scale |
| `range_match` | centrality inside the preferred band; outside the band scores 0 |
| `geographic_compatibility` | city → region → country plus mutual relocation openness; never an exact address |
| `readiness` | share of published projection fields |
