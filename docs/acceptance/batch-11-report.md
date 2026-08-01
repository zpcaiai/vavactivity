# Batch 11 Acceptance Report — Notification Center

Date: 2026-08-01

## Accepted scope

Batch 11 delivers a persisted notification domain rather than a UI-only inbox:

- versioned event inbox/subscriptions, encrypted payloads, deduplicated intents and dead letters;
- immutable multilingual template releases with review, approval, activation, preview, restricted test send and rollback;
- database-backed in-app notifications and unread count, read/all-read/archive flows and immediate bell refresh;
- email delivery attempts, bounded retry/backoff, Mailpit development adapter, provider webhook verification and idempotency;
- category/channel preferences, mandatory security/transactional rules, quiet hours, digest scheduling, consent and category-scoped unsubscribe;
- hard-bounce/complaint suppression, repeated-soft-bounce threshold, administrative lift reason and provider health state;
- reminder replanning and dispatch-time aggregate/version revalidation;
- governed campaigns with test-send, review, independent production approval, frozen safe audience, rate/batch controls, pause and cancel;
- notification manager/campaign editor/support roles, 33 notification permissions and redacted/audited administration views;
- user and administrator web routes, notification center, preference center and operations console.

## Verification evidence

| Gate | Result | Evidence |
| --- | --- | --- |
| Alembic | PASS | Local PostgreSQL is at `20260801_0040`; migrations `0035`–`0040` applied. |
| Seeds | PASS | 41 definitions, 246 baseline active localized/channel releases, 29 subscriptions, 3 reminder policies; permission registry reports 254 permissions and 27 roles. |
| Notification tests | PASS | 23 tests across unit, integration, provider, concurrency and security suites. |
| API regression | PASS | 179 API tests passed after the template transition/rollback regression was added. |
| Static analysis | PASS | Ruff across services, format check and mypy across API/worker passed; frontend lint and type checks passed. |
| User web tests/build | PASS | 5 files / 7 tests passed; production Vite build passed. |
| Admin web tests/build | PASS | 5 files / 6 tests passed; production Vite build passed (chunk-size warning only). |
| Browser acceptance | PASS | Chromium user flow passed persisted unread/read/archive/preferences; administrator flow passed dashboard/templates/subscriptions/campaign/provider views. |
| SMTP development path | PASS | A notification delivery changed Mailpit `SMTPAccepted` from 5 to 6 and the database delivery reached `sent`. |
| Template governance API | PASS | A new release completed draft → review → approved → active; the prior release was then restored through the rollback endpoint. |
| OpenAPI/client | PASS | OpenAPI was exported and the TypeScript API schema regenerated. |
| Docker images | PASS | `docker compose build api worker` completed and exported both pinned backend images. |

## Local database evidence

The acceptance database contained 41 template definitions, 252 releases (baseline plus acceptance versions), 29 subscriptions, 90 received events, 86 intents, 86 in-app notifications, 48 email deliveries, 32 provider events, 18 historical/active suppression rows, 3 reminder policies, and 430 notification audit events. These are mutable local acceptance counts, not production metrics.

## Honest release boundary

- External production email provider credentials, provider-specific webhook formats, reputation/warm-up and production deliverability are `NOT_RUN`.
- Production worker throughput, queue-lag SLO, multi-instance failover and campaign-scale load testing are `NOT_RUN`.
- Real customer consent/legal review, marketing policy approval and production campaign approval remain `NOT_CERTIFIED`.
- Local Mailpit acceptance proves the application SMTP path, not internet delivery or inbox placement.
- No production deployment or customer acceptance is claimed by this report.
