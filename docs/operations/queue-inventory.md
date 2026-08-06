# Queue inventory

| Queue | Work | Failure behavior |
|---|---|---|
| default | common outbox and domain work | retry with idempotency |
| commerce | payment reconciliation/entitlements | fail closed, no premature grant |
| activities/courses/counseling | service fulfillment | durable retry, human boundary retained |
| ai/knowledge/recommendations | model and retrieval jobs | safe degradation, no safety bypass |
| notifications | in-app/email delivery | in-app persists, provider retry/dead letter |
| privacy | export/erasure/retention | encrypted artifacts, audited checkpoints |
| safety | blocks, restrictions, appeals | highest priority, alert on propagation delay |
| media | scans/transforms/object operations | quarantine on uncertainty |

Alert on oldest-message age, retries, dead letters, worker heartbeat, and recovery slope—not queue length alone. Replays require permission, idempotency, reason code, and audit.
