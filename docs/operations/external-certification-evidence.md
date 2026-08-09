# External Certification Evidence Contract

Batch 29-32 controllers consume environment-bound evidence from directories supplied at
runtime. Policy manifests and simulation fixtures can never replace these files.

## Common envelope

Every evidence file is JSON and must contain:

```json
{
  "status": "PASS",
  "git_commit": "0123456789abcdef0123456789abcdef01234567",
  "artifact_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "completed_at": "2026-08-09T12:00:00Z"
}
```

`status` is `PASS` or `FAIL`. `git_commit` must exactly match the audited backend commit.
`artifact_sha256` is the SHA-256 digest issued by the evidence producer for its immutable raw
artifact. `completed_at` identifies when the external run completed. Missing files produce
`NOT_EVALUATED`; malformed, failed or cross-commit files produce `FAIL`.

## Batch 29 performance

Set `PERFORMANCE_EVIDENCE_DIR`. Required files are:

- `baseline.json`
- `load-test.json`
- `spike-test.json`
- `stress-test.json`
- `soak-test.json`

The controller combines each external result with its local workload, budget and simulation
checks. Both sides must pass.

## Batch 30 security

Set `SECURITY_EVIDENCE_DIR`. Required files are:

- `sast.json`
- `sca.json`
- `secret-scan.json`
- `iac-scan.json`
- `container-scan.json`
- `api-dast.json`
- `api-fuzz.json`
- `penetration-test.json`

Local threat-model, authorization, privacy, AI and Skill-sandbox checks remain mandatory in
addition to the external evidence.

## Batch 31 resilience

Set `RESILIENCE_EVIDENCE_DIR`. Required files are:

- `error-budget.json`
- `observability.json`
- `synthetic-monitor.json`
- `api-ha.json`
- `database-ha.json`
- `redis-worker-ha.json`
- `provider-resilience.json`
- `degradation.json`
- `chaos.json`
- `backup-restore.json`
- `dr-game-day.json`
- `incident-management.json`
- `resilience-tests.json`
- `resilience-security.json`

## Batch 32 final release

Set `FINAL_EVIDENCE_DIR`. Required files are:

- `quality-score.json`, with a `scores` object containing every required quality dimension and
  `overall`;
- `go-no-go.json`, with `security_posture.critical_open_findings`,
  `security_posture.unresolved_sev1_findings` and
  `security_posture.external_pen_test_last`;
- `approval-production-owner.json`, `approval-security-owner.json` and
  `approval-data-governance-owner.json`, each with `approved: true`, an `approval_role` equal
  to the filename role in underscore form, a non-empty `approver` and `approved_at`;
- `observation-24h.json`, `observation-7d.json` and `observation-30d.json`, each with
  `starts_at`, `ended_at`, `expected_ends_at` and `critical_events_detected`.

Batch 32 additionally requires all non-waivable release artifacts to report
`technical_status=PASS`, `production_certification=CERTIFIED` and `release_allowed=true`.
Until every check passes, its final report remains `NOT_CERTIFIED` and release remains blocked.
