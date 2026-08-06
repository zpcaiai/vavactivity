# Block propagation matrix

Batch 18 treats an active user block as a synchronous, mutual-visibility safety boundary. A browser-side hide is never accepted as enforcement.

| Surface | Write/read enforcement | Synchronous invalidation on block | Unblock behavior |
| --- | --- | --- | --- |
| Recommendation candidates and items | Trust & Safety gateway and pair exclusion | Candidate pairs and items invalidated; pair version advanced | Historical cards remain invalidated |
| Profile direct URL | Profile service calls the read-only safety gateway | Pair version makes cached decisions stale | A new request is required; no consent restored |
| Likes and mutual matches | Interaction gateway checks both users | Likes invalidated; match restricted/frozen | Historical likes and matches remain frozen |
| Invitations | Interaction gateway checks before send/read | Pending invitations cancelled | Invitations are not recreated |
| Contact grants and reveal tokens | Gateway before grant/reveal | Grants revoked and reveal tokens invalidated | Grants require new consent |
| Relationship journey | Relationship access uses the pair safety boundary | Journey frozen or ended and reminders suppressed | Journey is not automatically resumed |
| Activity directory and registration | Activity projections consume block/restriction decisions | Unsafe projections are invalidated; operations fail closed | New eligibility is evaluated on each request |
| Notifications | Recipient safety policy and outbox event | Non-essential pair notifications suppressed | Old notifications are not redelivered |
| Membership | Entitlements remain subordinate to Trust & Safety | No benefit can override a block or restriction | Entitlements still cannot restore consent |

Failure policy: if synchronous propagation or the central safety read fails, the affected interaction is denied, contact grants and tokens remain revoked, and a release-blocking regression test is required. Authentication, appeal, and data-rights access remain available where safe.
