# Feature flag operations

Flags start disabled in `draft`. The creator may change targeting using optimistic versioning but cannot approve their own draft. A different administrator with `system.feature_flags.approve` approves it; activation requires the approved state and `system.feature_flags.manage`. Every mutation is audited.

Flag codes under safety, privacy, payment, authorization, and encryption are rejected. Flags may shape optional experience only; they cannot change mandatory enforcement. Rollout starts with synthetic/internal cohorts, monitors error and safety metrics, and keeps a tested rollback value. Production target changes require a reason and peer review.
