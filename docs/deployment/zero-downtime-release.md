# Zero-downtime release

1. Build, scan, attest, sign, and record immutable image digests.
2. Verify the database change follows expand-migrate-contract and upgrade an empty database plus the previous release snapshot.
3. Back up and verify the current data plane.
4. Deploy the additive schema migration and backwards-compatible application to staging.
5. Pass staging smoke, complete E2E, security, privacy, payment, and block-propagation gates.
6. Obtain production approval and deploy with start-first rollout while monitoring error rate, latency, queue delay, and locks.
7. Stop expansion on alert. Roll application digest back when schema-compatible; otherwise keep traffic constrained and forward-fix.
8. Contract old schema only in a later release after every old workload and backfill is complete.

Profile-media storage v2 has a protocol-level compatibility boundary in
addition to its expand migration. Follow
[`profile-media-storage-v2.md`](profile-media-storage-v2.md): keep the feature
off through migration and the complete backend rollout, run its activation
gate, and never auto-rollback to a pre-0112 image after activation.

Keep the rejected release, logs, traces, manifest, and incident record. Never delete evidence to make a retry appear clean.
