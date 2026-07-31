# Course domain and authority boundaries

| Fact | Authority |
| --- | --- |
| Curriculum, versions, release and completion | Courses |
| Products, SKUs, prices and bundles sold | Catalog |
| Orders, payment and refunds | Commerce |
| Purchased access right | Entitlements |
| Stored media and provider processing state | Media/video provider |
| Enrollment, progress, attempts and certificates | Courses |

Paid access is projected only from active `course_access` entitlements. Browser
payment returns never activate learning. A bundle entitlement is expanded using
its immutable fulfillment snapshot, so later bundle edits do not change prior
purchases.

Published curriculum creates an immutable snapshot. Enrollments pin that
version, completed progress cannot be rolled back by stale devices, and answer
keys, responses, private object references and signed playback URLs are omitted
from public DTOs and ordinary audit payloads.

