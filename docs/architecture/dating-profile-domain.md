# Dating Profile Domain

## Separation of concerns

```
User                       account and login identity (Batch 2)
UserProfile                general personal data, protected date of birth (Batch 12)
DatingProfile              who I am, in a matchmaking context (Batch 13)
PartnerPreferenceProfile   who I hope to meet (Batch 13)
```

Nothing flows implicitly between these. An account email, a payment name or a counseling
intake answer is never copied into a dating profile.

## Record versus projection

```
raw dating profile
  → approved-version check
  → viewer relationship check
  → block / restriction check
  → view context
  → field sensitivity ceiling
  → member privacy rule
  → DatingProfileViewProjection
```

The frontend never receives a full profile to hide parts of. A client bug therefore cannot
leak a restricted field.

## Profile lifecycle

```
DRAFT → INCOMPLETE → READY_TO_SUBMIT → SUBMITTED → IN_REVIEW
                                                    ├── APPROVED → ACTIVE
                                                    ├── CHANGES_REQUESTED → DRAFT
                                                    └── REJECTED

ACTIVE ↔ PAUSED_BY_USER          member controlled
ACTIVE → SUSPENDED → ACTIVE      platform controlled, reason required
any    → DELETION_PENDING → ARCHIVED
```

`READY_TO_SUBMIT` is reached only when the backend says every required field is present.

## Version strategy

```
ACTIVE profile, approved version 4
member edits            → draft version 5
version 5 under review  → other members keep seeing version 4
version 5 approved      → approved version switches atomically
                        → projection rebuilds, caches drop
```

Changing one field therefore never makes a member vanish from recommendations, unless the
change raises a safety concern or the member pauses their own profile.

## Photo pipeline

```
upload request
  → validate declared type and size
  → decode and verify the image
  → reject a declared type that disagrees with the decoded format
  → rebuild from raw pixels (drops EXIF, GPS, ICC and XMP)
  → re-encode and thumbnail
  → non-identifying quality flags
  → REVIEW_REQUIRED
  → human decision
  → APPROVED
```

No biometric template is derived at any point and cross-site face search stays disabled.
Access is a short-lived token bound to one viewer; the storage object key never leaves the
backend, and deletion or rejection revokes outstanding tokens in the same transaction.

## View contexts

| Context | Sections released | Sensitivity ceiling |
| --- | --- | --- |
| `self` | all | highly restricted |
| `admin_review` | all but privacy | restricted |
| `recommendation_card` | basic, location, faith, photos | controlled public |
| `profile_detail` | + lifestyle, education, interests, values, narrative | confidential |
| `activity_directory` | basic, location, photos | controlled public |
| `mutual_match` | + family, values, vision | restricted |
| `introduction_accepted` | + relationship history, children | restricted |
| `ai_context` | basic, faith, lifestyle, values, vision | confidential, consent required |

Contact details appear in none of them. Contact exchange is a Batch 15 consent flow.

## Recommendation projection

Built only from the approved version, carrying normalised codes:

```
age bucket and age, country / region / city, gender and eligible partner genders,
faith codes, relationship intent, marital status, children status,
relocation willingness, language codes, lifestyle codes, indexed preference criteria
```

An unexpected key raises `DATING_PROJECTION_FIELD_NOT_ALLOWED` and the rebuild fails closed.
Names, contact details, exact birth dates, narratives, raw photo locations, counseling
records, AI transcripts, payment data and internal review notes can never appear.

Pool eligibility requires all of: profile `ACTIVE`, an approved version, an active account,
adult age, completeness above the recommendation threshold, an approved primary photo (when
required), matchmaking visibility granted, no security suspension and confirmed preferences.
Failing any one produces a reason code and removes the row.

## Events

Domain events are written to the shared outbox: creation, update, version creation, submission,
review start, change request, approval, activation, pause, reactivation, suspension, restore,
archive, the photo lifecycle, primary-photo change, preference and privacy updates, completeness
recalculation and projection update or removal.

Projection rebuilds are queued through `dating_profile_projection_jobs` with a dedupe key, so a
burst of events collapses to a single rebuild.

## Audit

`matchmaking_audit_events` records entity identifiers, field codes, versions and decisions.
It never stores narrative text, photo content or full preference criteria.
