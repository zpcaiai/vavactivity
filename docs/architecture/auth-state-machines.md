# Authentication state machines

## User

`pending_verification -> active -> locked|suspended|deletion_pending -> deleted`

An expired temporary lock may return to `active`; administrator suspension requires an
audited restore. Deleted accounts never receive tokens.

## Session

`active -> replaced -> revoked` for rotation and compromise handling.

`active -> revoked` for logout, password reset, administrator action or account suspension.

`active -> expired` when the refresh lifetime ends. Session evidence is retained.
