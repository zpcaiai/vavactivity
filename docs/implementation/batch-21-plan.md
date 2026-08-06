# Batch 21 implementation and verification record

## Implemented scope

Batch 21 adds the platform-wide quality control plane that Batches 22–32 report into: a quality constitution, a versioned requirement registry, a capability inventory, a bidirectional traceability graph, page/API/data/test mappings, business-closure matrices, exception-scenario coverage, deterministic gap and orphan detection, quality risks, expiring waivers with separation of duties, release-bound evidence with integrity checks, a declarative release-gate engine, structural completeness scoring with an unconditional veto rule, and the quality administration APIs.

This batch adds no business behaviour. It registers the requirements and evidence produced by other batches, detects missing coverage and blocks release when critical quality conditions are not met.

## Verification order

1. Validate `quality-manifest.yaml`, the module manifest and the migration chain (`make quality-manifest-check`).
2. Apply migration `20260806_0087` and seed governed definitions (`make quality-migrate quality-seed`).
3. Build the artifact inventory and traceability checks (`make quality-sync quality-trace-check`).
4. Validate business closure and detect gaps (`make quality-closure-check quality-gap-check`).
5. Run the pure-domain, gate, security and concurrency suites (`make quality-test quality-gate-test quality-security-test`).
6. Evaluate a reproducible offline release decision (`make quality-gate-evaluate`).
7. Build the evidence bundle and release report (`make quality-evidence-build quality-release-report`).

## Deliverables

| Area | Path |
|---|---|
| Domain algorithms | `services/api/src/vav/modules/quality/domain.py` |
| Request/response schemas | `services/api/src/vav/modules/quality/schemas.py` |
| Application services | `services/api/src/vav/modules/quality/service.py` |
| Admin APIs | `services/api/src/vav/modules/quality/admin_router.py` |
| Module contract | `services/api/src/vav/modules/quality/module.yaml` |
| Migration | `services/api/migrations/versions/20260806_0087_quality_governance.py` |
| Seed | `services/api/src/vav/cli/seed_quality.py` |
| Control CLI | `scripts/quality/control.py` |
| Offline gate evaluator | `scripts/quality/evaluate_release_gate.py` |
| Tests | `tests/quality/{unit,gates,security,integration,concurrency}` |
| Skills | `skills/batch-21/` |
| Make fragment | `make/batch-21.mk` |
| Constitution | `docs/quality/quality-constitution.md`, `quality-manifest.yaml` |

## Database

Revision `20260806_0087` (`down_revision = 20260806_0086`) creates:

`quality_requirements`, `quality_capabilities`, `quality_trace_nodes`, `quality_trace_links`,
`quality_pages`, `quality_api_operations`, `quality_business_flows`, `quality_business_flow_steps`,
`quality_exception_scenarios`, `quality_gaps`, `quality_risks`, `quality_gate_definitions`,
`quality_waivers`, `quality_evidence`, `quality_gate_runs`, `quality_release_evaluations`,
`quality_certifications`.

Requirement and capability codes are unique; trace nodes are unique per `(node_type, node_code, version)`; trace links are unique per `(source, target, relationship)`; gate runs are unique per `(gate_definition_id, release_version, environment)`.

## Core algorithms

- **Traceability graph** — `analyze_traceability` walks the required chain Requirement → Capability → Business Flow → Page/API → Service → State Machine → Table → Event → Permission → Metric → Test → Evidence and reports missing node types and unverified required links. `traceability_downstream` and `traceability_upstream` answer both directions; `detect_trace_cycles`, `detect_dangling_links` and `unreachable_nodes` protect graph integrity so an artifact can never justify itself.
- **Gap detection** — one pure detector per gap class (orphan page, mock-only page, orphan API, missing permission, missing audit, missing idempotency, orphan/unconsumed event, orphan permission, orphan table, missing retention, missing erasure path, untested state, missing terminal state, missing admin capability, missing exception path, missing metric, missing notification, missing test, missing evidence, missing owner, unresolved dead letter, unimplemented/unverified requirement). `detect_all_gaps` aggregates them into deterministic, deduplicated `QualityFinding` records.
- **Business closure matrix** — every flow is evaluated against ten mandatory dimensions (entry, in-progress, success/failure/cancel/expiry terminals, manual intervention, compensation, user-visible state, admin actionable). Absent or unknown dimension keys fail closed.
- **Release gates** — the condition DSL accepts only `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `contains`, `all_passed`, `none_open` over a restricted metric-name grammar. Any Blocker failure or non-passing non-waivable gate is `NO_GO`; a valid waiver on a Required gate yields `CONDITIONAL_GO`; everything else must pass for `GO`.
- **Evidence** — bound to release version, Git commit and environment, with SHA-256 integrity, acceptance status and expiry. `select_gate_evidence` returns `None` plus explicit reasons when nothing usable exists, so a missing report can never be read as a pass.
- **Structural score** — weights of 20/15/20/15/10/15/5 across trace coverage, capability mapping, business closure, exception paths, admin support, tests and evidence, and ownership. Unreported or unverifiable dimensions score zero. Any `NonWaivableFailure` forces `NO_GO` regardless of the total.

## API surface

All routes are mounted under `/api/v1/admin/quality` and guarded by `require_permission("quality.*")`. Dashboard, requirements, capabilities, traceability nodes/links, business flows, exception scenarios, gaps, risks, waivers, evidence, gate definitions, gate runs, release evaluation, release detail, certification and audit endpoints are exposed.

## Gates and acceptance

- Blocker requirement trace coverage and critical requirement verification must be 100 percent.
- Critical business-flow closure must be 100 percent with zero unrecoverable states.
- Critical orphan pages, orphan APIs, unresolved critical dead letters and open critical risks must be zero.
- `GATE-SECURITY-CRITICAL`, `GATE-BLOCK-PROPAGATION`, `GATE-PRIVACY-ERASURE-COMPLETENESS`, `GATE-PAYMENT-ENTITLEMENT-INTEGRITY`, `GATE-RESTORE-DRILL` and `GATE-DATA-CRITICAL-RECONCILIATION` can never be waived.
- Production releases do not accept `CONDITIONAL_GO`.

## Boundaries with other batches

Batch 21 owns `services/api/src/vav/modules/quality/{domain,schemas,service,admin_router}.py`, migration `0087`, `scripts/quality/`, `tests/quality/`, `skills/batch-21/` and `make/batch-21.mk`. Batch 22 reuses the `quality` module package for design-system routers (`design_*.py`) and migration `0088`. Batches 23–32 register their evidence, capabilities and gate results through the APIs above rather than adding new control planes.

## Evidence policy

Local architecture and unit gates passing means the control plane is implemented; it does not assert production certification. `production_certification` stays `NOT_CERTIFIED` until independent security, restore-drill, UAT and production-approval evidence is registered and accepted.

## Not complete in this batch

- Source scanners for Vue routes and API usage remain manifest-driven rather than AST-driven; `scripts/quality/control.py` derives the inventory from manifests and directory structure.
- Admin-web quality pages and `e2e/admin-quality` cover the dashboard entrypoint only; the per-node traceability graph visualisation is deferred.
- Evidence artifacts are referenced and checksummed but not stored by this module; object storage remains the owning batch's responsibility.
