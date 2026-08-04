# Batch 13 Acceptance Report — Dating Profiles, Preferences and Review

Date: 2026-08-04

## Accepted scope

Batch 13 delivers the matchmaking profile domain that Phase 2 depends on:

- one dating profile per eligible member, with a `profile_number` and the full thirteen-state
  lifecycle enforced by an explicit transition table;
- backend-authoritative adult eligibility, computed from the Batch 12 protected date of birth —
  the matchmaking domain stores only a source marker, never a second copy of the value;
- a versioned schema release (64 field definitions) and 37 controlled taxonomies with localized
  labels, where value codes are the business identifiers and retired values are disabled rather
  than deleted;
- basic, location, faith, relationship-history, family, children, lifestyle, education and
  communication detail, with encrypted free-text summaries;
- per-locale narratives with configured length limits, outright rejection of contact details and
  external links, risk screening that routes to human review, and required member confirmation of
  AI-assisted text;
- private photo handling: decode verification, spoofed-MIME rejection, metadata stripping by
  re-encoding from raw pixels, thumbnails, duplicate detection, one live primary photo, a review
  queue and short-lived viewer-bound access tokens;
- partner preferences restricted to 20 approved criteria, with explicit hard constraints,
  no silent relaxation, contradiction detection and owner-only visibility;
- field-level privacy across eight view contexts, each with its own section allow-list and
  sensitivity ceiling, and no contact details in any of them;
- completeness scored by the backend from the active policy, with required fields carrying a
  fixed 80% share so a missing mandatory field always blocks submission;
- immutable submitted and approved versions enforced by database triggers, draft revisions that
  never disturb the version other members are seeing, and atomic approval switching;
- field- and photo-level review decisions, encrypted internal notes, mandatory reasons for
  rejection and suspension, optimistic locking against concurrent reviewers, and member-facing
  feedback that carries only safe messages;
- de-identified recommendation projections built solely from the approved version, with an
  allow-list that fails closed, idempotent rebuilds and a deduplicating job queue;
- 25 `matchmaking.*` permissions and three roles, where `profile_reviewer` deliberately lacks
  sensitive-field, original-photo and suspension rights;
- a ten-step member journey and an administrator review center.

## Verification evidence

| Gate | Result | Evidence |
| --- | --- | --- |
| Alembic | PASS | Local PostgreSQL is at `20260804_0053`; migrations `0047`–`0053` applied from a clean schema. |
| Seeds | PASS | Schema release `vav-dating-profile@1.0.0` with 64 fields, 37 taxonomies and 3 profile fixtures; permission registry reports 320 permissions and 34 roles. |
| Dating-profile tests | PASS | 154 tests — 93 unit, 38 integration, 7 concurrency, 16 security. |
| API regression | PASS | 348 tests pass from a clean database and empty Redis; the 194-test Batch 1–12 baseline is unchanged. |
| Static analysis | PASS | Ruff check and format across services, mypy strict across API and worker (164 files). |
| Frontend | PASS | ESLint and `vue-tsc` clean for both apps; 7 user-web and 6 admin-web unit tests pass. |
| OpenAPI contract | PASS | Regenerated; 84 dating-profile / matchmaking references present in `packages/contracts/openapi.json` and the TypeScript client. |
| Manifest | PASS | `validate_manifest.py` reports 21 modules, 2 phases, 49 fail-closed decisions. |

## Security and privacy results

Each of these is covered by an automated test, not only by review:

| Guarantee | Test |
| --- | --- |
| A member cannot edit another member's profile | `test_a_member_cannot_edit_another_members_profile` |
| Draft profiles are invisible to other members | `test_draft_profiles_are_invisible_to_other_members` |
| Only the approved version reaches other members | `test_only_the_approved_version_reaches_other_members` |
| A suspended profile leaves the pool and the view | `test_suspended_profile_is_not_visible_and_leaves_the_pool` |
| Preferences never reach another member | `test_partner_preferences_are_never_exposed_to_other_members` |
| Contact details appear in no context | `test_contact_details_never_appear_in_any_member_view` |
| Encrypted summaries never reach another member | `test_encrypted_private_summaries_never_reach_another_member` |
| AI context is refused without consent | `test_ai_context_is_refused_without_consent` |
| Rejected photos are not served | `test_rejected_photo_is_not_served_to_other_members` |
| Storage object keys stay in the backend | `test_photo_storage_keys_never_leave_the_backend` |
| EXIF does not survive upload | `test_exif_gps_data_does_not_survive_upload` |
| Projections carry no prohibited field | `test_recommendation_projection_contains_no_prohibited_field` |
| Internal notes are encrypted and never returned | `test_review_internal_notes_are_encrypted_and_never_returned` |
| Field overrides are enforced by the backend | `test_field_visibility_override_is_enforced_by_the_backend` |
| Admin and member views are generated separately | `test_admin_and_member_views_are_generated_separately` |
| View tokens are bound to one viewer | `test_view_token_belongs_to_the_requesting_viewer_only` |

## Concurrency results

| Race | Outcome |
| --- | --- |
| Three simultaneous profile creations | Exactly one profile; the others get `DATING_PROFILE_ALREADY_EXISTS`. |
| Stale field edit | Rejected with `DATING_PROFILE_VERSION_CONFLICT`. |
| Four simultaneous primary-photo uploads | Exactly one live primary photo. |
| Three simultaneous primary promotions | Exactly one live primary photo. |
| Two reviewers approving the same case | One succeeds; the other gets `DATING_REVIEW_VERSION_CONFLICT`. |
| Five duplicate projection events | Collapse to a single pending job. |
| Four simultaneous rebuilds | Converge on one projection row. |

## Deliberate boundaries

- Hard filtering, scoring, ranking and explanations belong to Batch 14; this batch only
  publishes the projection they will read.
- Like, skip, mutual match, introductions and contact exchange belong to Batch 15. Contact
  exchange status is therefore hard-coded to `not_exchanged` in every projection.
- Reporting, blocking and fraud handling belong to Batch 18. Block checks are written
  defensively so they activate automatically once `user_blocks` exists.
- Automated photo checks are non-identifying quality flags only. No biometric template is
  created, and a "suspected impersonation" reason code routes to human review rather than an
  automated fraud verdict.

## Open decisions recorded

`dating_gender_policy`, `dating_relationship_intent_eligibility`, `dating_faith_taxonomy_scope`,
`dating_profile_default_visibility`, `dating_photo_moderation_provider` and
`dating_profile_review_staffing` are registered as undecided in `project-manifest.yaml` and the
decision register. Each is implemented as an optional field with a restricted default; none is
encoded as a permanent social or theological rule.

## Not executed in this environment

`make dating-profile-verify` includes the two Playwright suites, which need the full Docker
Compose stack with both web apps running. The specs are committed under
`e2e/user-dating-profile` and `e2e/admin-dating-profile`; they were not executed here because
verification ran against a native PostgreSQL/Redis pair rather than Compose.
