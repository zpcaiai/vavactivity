# Complete E2E acceptance matrix

`make complete-e2e` runs 19 required entrypoints and 55 deterministic browser tests against the assembled runtime.

| Entry | Journey | Primary evidence |
|---:|---|---|
| 01 | registration, verification, login, session | authenticated browser session |
| 02 | CMS and public locale/contact | published structured content |
| 03 | catalog, quote, cart, checkout | signed webhook-only fulfillment |
| 04 | payment and entitlement operations | reconciliation visibility |
| 05–07 | activities, courses, counseling | real domain service fulfillment |
| 08 | consented AI and admin safety | citations/tools/referral boundary |
| 09 | notification and preferences | durable in-app/provider operations |
| 10–13 | dating profile, recommendation, mutual match, introduction/contact | privacy projections and mutual consent |
| 14 | relationship journey | bilateral transitions and redacted ops |
| 15 | membership | commerce authority and quota boundaries |
| 16 | report/block | propagation and independent safety review |
| 17–18 | privacy export and erasure | reauthentication, minimization, governed execution |
| 19 | system operations | redacted status, RBAC, four-eyes controls |

Fixtures are synthetic; payment, email, and AI providers are deterministic fakes. The suite controls worker completion by polling, not long sleeps. A local PASS does not replace real provider, managed backup, or production evidence.
