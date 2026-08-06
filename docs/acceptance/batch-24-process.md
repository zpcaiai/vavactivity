# Batch 24 acceptance

- Offline registry, graph and simulation gates must pass.
- PostgreSQL migration, downgrade/re-upgrade and idempotent seed must pass.
- Unit, integration, concurrency, compensation and security suites must pass.
- Admin browser E2E is separate external evidence and remains `NOT_RUN` until executed against the full stack.
- Production status remains `NOT_CERTIFIED` until all critical domains have independent production-bound certification.

Current local evidence (2026-08-06): migration 0089→0090, downgrade and re-upgrade PASS; seed executed twice PASS; 18 backend process tests PASS; 16 admin test files / 27 tests PASS; admin typecheck and production build PASS; 16 process manifests, 6 state machines and 8 simulations PASS. Browser E2E, provider recovery, business-owner acceptance and production observation remain `NOT_RUN`.
