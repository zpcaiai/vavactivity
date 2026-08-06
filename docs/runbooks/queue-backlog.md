# Queue backlog

## Symptoms and impact

Oldest-message age, retries, and dead letters rise; user-visible asynchronous results are delayed.

## Detect

Break down backlog by queue, task, age, retry code, worker heartbeat, database contention, and provider dependency.

## Immediate containment

Pause bulk/campaign workloads, protect safety/payment/privacy priorities, cap retries, and do not discard durable work.

## Recovery

Fix the cause, scale the affected worker within downstream capacity, replay idempotently in bounded batches, and watch recovery slope.

## Verification and rollback

Confirm queue age returns to SLO with no duplicate entitlement/quota/match/notification effect. Reduce concurrency if locks or provider errors grow.

## Communication and review

Publish affected functions and delay estimate. Review task cost, indexes, partitioning, priority, and capacity baseline.
