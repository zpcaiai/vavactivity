# Redis unavailable

## Symptoms and impact

Rate limiting, cache, broker, and worker coordination degrade; PostgreSQL business truth remains intact.

## Detect

Check Redis ping/latency, broker reconnects, queue heartbeats, API errors, and the Redis availability alert.

## Immediate containment

Throttle enqueue sources, prevent retry storms, and keep payment/safety/privacy decisions fail closed. Never treat a cache miss as authorization.

## Recovery

Restore the cluster/network, rebuild caches from PostgreSQL, resume priority queues first, and replay durable outbox work idempotently.

## Verification and rollback

Run smoke, verify queue age declines, confirm no duplicate webhook/match/quota effect, and re-isolate Redis if corruption or flapping returns.

## Communication and review

Report degraded functions and backlog ETA. Review memory policy, persistence assumptions, reconnect jitter, and recovery capacity.
