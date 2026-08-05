# Batch 14 Acceptance Report — Bidirectional Recommendation Engine

Date: 2026-08-04

## Accepted scope

Batch 14 turns Batch 13's approved projections into recommendations:

- a recommendation pool recomputed from the approved projection, the account, the profile
  status, adult eligibility and the member's own pause switch, with a reason code for every
  exclusion;
- canonical `(low, high)` candidate pairs — reversing the arguments cannot create a second
  record — with SQL recall on normalised columns and a bounded per-member candidate limit;
- safety, block, active-relationship, invitation, skip-cooldown and privacy exclusions applied
  before scoring, with a moderation failure failing closed;
- a bidirectional hard-constraint engine over 14 supported criteria plus two platform rules,
  member-controlled unknown-value policies, member-permitted relaxation that is disclosed, and
  never-relaxable adult eligibility, relationship eligibility, safety blocks and privacy consent;
- an 18-feature approved registry across 10 groups, where appearance, wealth, health,
  ethnicity, personality, AI conversations, counselling records and payment behaviour are
  structurally impossible inputs and `assert_registry_is_clean()` fails closed;
- directional soft scoring in integer basis points, member importance as weight, `required`
  never double counted, missingness lowering confidence rather than scoring zero, and a
  confidence formula that prevents a single matching field from producing a confident perfect
  score;
- bidirectional composition using the weaker direction plus a geometric mean with asymmetry
  suppression, minimum directional and bidirectional floors, balance and mutual strengths;
- deterministic ranking with novelty, exposure, diversity and exploration adjustments stored
  separately from the compatibility score, unique contiguous ranks, and diversification that
  only reorders already-qualified candidates;
- rule-backed explanations with mutual strengths, the member's own matched preferences, topics
  to explore, information gaps, relaxation notices and an approved caveat — no percentage, no
  internal weight, no other member's preferences, no probability or guarantee — plus a bounded
  optional AI rewrite that falls back to the template;
- immutable batches bound to strategy, profile, preference and privacy versions, idempotent per
  period, atomically activated, with display-time safety, privacy, status and exclusion
  rechecks;
- idempotent exposure events that distinguish a loaded card from a seen one, daily receive and
  per-profile shown limits enforced with a locked conditional update, repeat-exposure cooldown
  and popularity caps;
- cold-start classification, transparent defaults, guidance, exploration slots that still pass
  every check, and honest empty results with aggregate diagnostics;
- typed idempotent feedback where blocks and reports remove candidates immediately and are not
  learning data, skips start a cooldown, negative reasons stay encrypted, and member tuning is
  bounded, explainable and resettable;
- offline evaluation whose correctness metrics block a release, and experiments that are
  disabled by default, require approval, pin strategies, assign stably and stop on a guardrail;
- 33 `recommendations.*` permissions and three roles, where `recommendation_operator`
  deliberately lacks sensitive-candidate, sensitive-feedback, activation and experiment-start
  rights;
- member pages (list, detail, preferences, history, transparency) and an administrator
  supervision centre with no control that could force a pairing, edit a score or bypass a rule.

## Verification evidence

| Gate | Result | Evidence |
| --- | --- | --- |
| Alembic | PASS | Local PostgreSQL is at `20260804_0059`; migrations `0054`–`0059` applied from `0053`. |
| Seeds | PASS | 18 features and the baseline strategy `baseline-bidirectional-v1@1.0.0` seeded, evaluated and activated; 3 evaluation datasets; 6 synthetic recommendation-eligible fixtures. |
| Pipeline | PASS | `build_recommendation_pool` → 6 pool entries; `generate_recommendation_fixture_batches` → 6 active batches, 3 items each, 0 skipped. |
| Recommendation tests | PASS | 195 tests — 96 unit, 50 integration, 6 concurrency, 26 security, 17 fairness. |
| Offline evaluation | PASS | `run_recommendation_evaluation` measured 18 delivered items: hard-constraint, eligibility, blocked-pair, privacy, safety, contact-leakage and unapproved-exposure rates all `0` bps. |
| Static analysis | PASS | Ruff check and format across `services`, mypy strict across API and worker (190 files). |
| Frontend | PASS | ESLint and `vue-tsc` clean for both apps; user-web 17 tests, admin-web 9 tests. |
| OpenAPI contract | PASS | Regenerated; 129 recommendation references in `packages/contracts/openapi.json` and the TypeScript client. |
| Manifest | PASS | `validate_manifest.py` reports 21 modules, 2 phases, 56 fail-closed decisions. |
| E2E | AUTHORED, NOT RUN | 17 spec files / 45 tests discovered by `playwright test --list`; execution needs the Docker stack, which this environment does not provide. |

## Security and privacy results

Each guarantee is covered by an automated test, not only by review:

| Guarantee | Test |
| --- | --- |
| A blocked pair is never generated and never shown | `test_a_blocked_pair_is_never_generated_or_shown` |
| A safety exclusion survives regeneration | `test_a_permanent_safety_exclusion_survives_regeneration` |
| A suspended account leaves generation and display | `test_a_suspended_account_disappears_from_generation_and_display` |
| A draft profile never enters the pool | `test_a_draft_profile_never_enters_the_pool` |
| Cards carry no contact detail or exact birth date | `test_items_never_carry_contact_details` |
| An unexpected snapshot field fails closed | `test_an_unexpected_snapshot_field_fails_closed` |
| The member view exposes no score or other preferences | `test_the_member_view_hides_scores_and_other_preferences` |
| Scores stay server-side | `test_stored_items_keep_scores_server_side_only` |
| No feature can read AI, counselling or payment data | `test_no_feature_can_read_ai_counselling_or_payment_data` |
| A member reaches only their own batches and items | `test_another_member_cannot_read_or_act_on_someone_elses_item` |
| Moderation failure fails closed | `test_a_moderation_failure_denies_the_pair` |
| Fail-closed cannot be switched off | `test_failing_closed_cannot_be_switched_off` |
| Caches are scoped per member and per version | `test_cache_keys_are_scoped_per_member_and_per_version` |

## Concurrency results

| Race | Test |
| --- | --- |
| Both directions generating at once | `test_both_directions_generating_at_once_produce_one_pair` |
| Three workers generating one daily batch | `test_two_workers_produce_one_daily_batch` |
| Parallel budget reservation | `test_concurrent_reservations_never_exceed_the_daily_limit` |
| Refresh cannot buy capacity | `test_a_refresh_cannot_buy_extra_capacity` |
| Duplicate feedback under concurrency | `test_concurrent_feedback_events_deduplicate` |
| Profile change during a live batch | `test_a_privacy_change_invalidates_an_unseen_item` |

## Regression

`tests/matchmaking_profiles` (Batch 13) and the Batch 1–12 suites were re-run. Two failures
remain in this environment — `content/test_draft_page_is_not_public` and
`ai_assistant/test_write_tool_requires_matching_single_use_user_confirmation` — both caused by
reusing one long-lived local database across many runs (a seeded draft page was published by an
earlier test, a single-use confirmation token was already consumed). Neither touches the
recommendation module; CI resets volumes between runs and both pass from a clean database.

## Open items

- E2E specs are authored but unexecuted here; run `make recommendation-user-e2e` and
  `make recommendation-admin-e2e` against the Docker stack before release.
- Every default in the decision register (weights, thresholds, exposure limits, exploration,
  fairness thresholds) is an engineering baseline awaiting a business decision.
- `recommendation_pair_exclusions` is the contract Batch 15 and Batch 16 write into for
  likes, invitations and relationship state; Batch 18 will replace the interim moderation
  gateway that currently reads Batch 6 interaction restrictions.
