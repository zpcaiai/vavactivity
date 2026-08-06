# Journey and task registry

The canonical task and journey definitions are `config/experience/tasks.yaml` and `config/experience/journeys.yaml`. Task deduplication uses `(user_id, deduplication_key)`. Waiting for the member, another party, the platform and an external provider are separate states.

Journey instances are resumable projections. `authoritative_state_version` must advance before the experience layer changes a projected step. The experience module cannot accept invitations, confirm relationship stages, make purchases, relax preferences or share private data.

Success, cancellation, expiry and invalidation are terminal. Active, blocked and waiting steps always expose a current route, fallback and contextual help.
