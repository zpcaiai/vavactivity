# Batch 13 Implementation Plan — Dating Profiles, Preferences and Review

Batch 13 adds the matchmaking profile domain on top of the Batch 12 privacy control plane.
Identity owns the account, Privacy owns the protected date of birth and field-visibility
rules, Media owns storage, and the new `matchmaking_profiles` module owns everything that
describes a member in a matchmaking context.

## Module boundary

| Concern | Owner |
| --- | --- |
| Account, login, RBAC | Batch 2 identity |
| General profile, protected date of birth, consent, field visibility | Batch 12 privacy |
| Media storage and object keys | Batch 3 media |
| Dating profile, preferences, photos, review, projections | Batch 13 matchmaking_profiles |
| Hard filtering, scoring, ranking, explanations | Batch 14 |
| Like, skip, mutual match, introductions, contact exchange | Batch 15 |
| Reporting, blocking, fraud and advanced moderation | Batch 18 |

Dating profiles never copy account email, payment names or counseling intake data.

## Delivery slices

1. **Schema and taxonomy registry** — versioned field manifest, field definitions,
   controlled vocabularies and localized labels. An active release is immutable; a retired
   value is disabled rather than deleted so historical profiles stay interpretable.
2. **Profile domain and lifecycle** — one profile per member, `profile_number`, the
   thirteen-state lifecycle, immutable versions with checksums, and core/location detail.
3. **Faith, relationship history, family and lifestyle** — restricted-by-default detail
   tables with encrypted free-text summaries.
4. **Narratives** — per-locale rows with configured length limits, contact-detail rejection
   and risk screening that routes to human review rather than a silent verdict.
5. **Photos** — decode, metadata strip, re-encode, thumbnail, duplicate detection, a single
   live primary photo, review queue and short-lived viewer-bound access tokens.
6. **Partner preferences** — approved criteria only, explicit hard constraints, no silent
   relaxation, contradiction detection, private to the owner and the recommendation engine.
7. **Field privacy and viewer projections** — eight view contexts, each with its own section
   allow-list and sensitivity ceiling. Contact details are never released.
8. **Completeness and versions** — required fields carry a fixed share of the score, a missing
   mandatory field always blocks submission, and snapshots preserve the policy version.
9. **Submission and review** — immutable submitted version, review case, field and photo
   decisions, change requests that open a new draft, approval that switches the displayed
   version atomically, suspension and restoration.
10. **Recommendation projections** — de-identified, approved-version-only rows with an
    allow-list that fails closed, an idempotent rebuild and a deduplicating job queue.
11. **Member and administrator web** — a ten-step stepper and a review center.
12. **Tests** — unit, integration, concurrency, security and E2E suites.

## Data model

Seven migrations, `20260804_0047` through `20260804_0053`:

| Migration | Tables |
| --- | --- |
| 0047 | `dating_profile_schema_releases`, `dating_profile_field_definitions`, `dating_taxonomies`, `dating_taxonomy_localizations` |
| 0048 | `dating_profiles`, `dating_profile_versions`, `dating_profile_core_details` |
| 0049 | faith, relationship-history, family, lifestyle detail and `dating_profile_narratives` |
| 0050 | `dating_profile_photos`, `dating_profile_photo_view_tokens` |
| 0051 | `partner_preference_profiles`, `partner_preference_criteria` |
| 0052 | completeness snapshots, review cases, review items, `matchmaking_audit_events` |
| 0053 | `dating_profile_recommendation_projections`, `dating_profile_projection_jobs` |

Database-level guarantees rather than application-only checks:

- `uq_active_dating_schema_release` — one active release per schema code.
- `dating_schema_release_immutable` — an active release cannot be edited.
- `dating_profile_version_immutable` — a submitted or approved snapshot cannot be rewritten.
- `uq_dating_profile_primary_photo` — one live primary photo per profile.
- `uq_dating_projection_job_pending` — duplicate rebuild events collapse to one job.

## Backend structure

```
services/api/src/vav/modules/matchmaking_profiles/
├── domain.py           # enums, state machines, sensitivity map, prohibited fields
├── taxonomies.py       # field manifest, controlled vocabularies, approved criteria
├── completeness.py     # backend-authoritative scoring
├── content_safety.py   # narrative screening
├── photos.py           # decode, metadata strip, re-encode, quality flags
├── preferences.py      # criterion validation and contradiction detection
├── privacy_view.py     # viewer-context projections
├── projections.py      # recommendation projection construction and eligibility
├── service.py          # profile lifecycle, fields, photos, versions, projections
├── review.py           # review workflow, suspension, member feedback
├── schemas.py          # request models
├── router.py           # member API
└── admin_router.py     # administrator API
```

## RBAC

25 `matchmaking.*` permissions and three roles. `profile_reviewer` deliberately lacks
`matchmaking.profiles.sensitive.read`, `matchmaking.photos.original.read`,
`matchmaking.preferences.sensitive.read` and `matchmaking.profiles.suspend`;
`profile_review_lead` adds escalation, suspension, restoration and sensitive reads;
`matchmaking_data_steward` owns schemas, taxonomies, completeness policy and projections.

## Open decisions

Gender policy, relationship-intent eligibility, faith taxonomy scope, default profile
visibility and the contact-exchange policy remain undecided. Each is implemented as an
optional field with a restricted default, and none is encoded as a permanent social or
theological rule.
