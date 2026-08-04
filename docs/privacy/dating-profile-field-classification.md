# Dating Profile Field Classification

Batch 13 registers eleven data domains with the Batch 12 privacy control plane. Every field
in the active schema release gets a `user_field_visibility_rules` row at profile creation,
seeded from the schema default — strict mode means the schema default is a ceiling, never a
floor.

## Registered domains

| Domain | Sensitivity | Notes |
| --- | --- | --- |
| `dating_profile.basic` | Controlled public | Display name, gender, relationship intent, age display mode |
| `dating_profile.location` | Confidential | City level only; a street address is never collected |
| `dating_profile.faith` | Restricted | Never presented or scored as spiritual quality |
| `dating_profile.relationship_history` | Restricted | Former partners are never identifiable |
| `dating_profile.children` | Restricted | Children are never personally identifiable |
| `dating_profile.family` | Restricted | No precise address may be inferred |
| `dating_profile.lifestyle` | Confidential | Financial attitude codes only, never bank or asset records |
| `dating_profile.narratives` | Controlled public | Contact details rejected at write time |
| `dating_profile.photos` | Restricted | Originals private, access token-gated |
| `dating_profile.partner_preferences` | Restricted | Owner and recommendation engine only |
| `dating_profile.review_notes` | Highly restricted | Encrypted, never returned by any API |

## Encryption at rest

These values are stored encrypted and are readable only by their owner:

- `faith.faith_journey_summary`
- `relationship_history.history_summary`
- `family.family_summary`
- profile version snapshots
- review internal notes and internal summaries
- photo moderation reports

## Never collected

- Precise home address
- Bank balances, asset schedules or income evidence
- Government identity numbers within the matchmaking domain
- Biometric templates derived from profile photos
- Third-party personal data without a basis

## Never released to another member

In any view context, including mutual match and accepted introduction:

- email, phone or messaging handles
- exact date of birth
- full narrative text outside the contexts that release it
- partner-preference criteria
- photo storage object keys
- review internal notes
- security or moderation case detail

## Consent dependencies

| Capability | Required consent |
| --- | --- |
| Entering the recommendation pool | `visible_in_matchmaking` privacy setting |
| AI reading the dating profile | `allow_profile_use_by_ai` (Batch 12 `ai_profile_context_access`) |
| Contact exchange | Batch 15 mutual confirmation; never automatic |

Withdrawing matchmaking visibility removes the projection on the next rebuild, which is
queued immediately by the privacy update endpoint.

## Administrative access

`matchmaking.profiles.read` grants the reviewer projection, which excludes contact details,
AI transcripts, counseling records, payment data and credentials. Reading restricted history
or preference detail requires `matchmaking.profiles.sensitive.read` or
`matchmaking.preferences.sensitive.read`; viewing an original photo requires
`matchmaking.photos.original.read`. Every administrative profile read writes a
`matchmaking.profile.sensitive_read` audit event recording whether the sensitive permission
was actually held.
