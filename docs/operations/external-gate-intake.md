# External gate intake

This control plane turns production-certification prerequisites into executable,
fail-closed checks. It does not create legal authorization, independent-test
evidence, real devices, cloud privileges or accountable owner approvals.

## Workflow

1. Run `make external-certification-init` once. The generated YAML contains
   environment-variable references only; never put credentials in the file.
2. Keep `certification_target: current_production` to certify the deployed
   Render/Vercel pair. Selecting `latest_feature` is rejected until both feature
   artifacts have production deployment IDs, and starts new observation windows.
3. Run `make external-certification-lock CERTIFICATION_INTAKE=...`. Distribute
   the resulting target fingerprint to every approver and external tester.
4. Fill the written authorization, disposable-account, device, infrastructure,
   approval and load-window sections. Attach evidence outside Git and record its
   SHA-256. Export only the referenced credential environment variables.
5. Run `make external-certification-preflight CERTIFICATION_INTAKE=...`.
   `BLOCKED` lists each missing external fact. `READY_FOR_EXTERNAL_EXECUTION`
   permits only the described tests during their windows; it is not certification.

## Safety properties

- Git commits, deployment IDs, URLs, release version and artifact kind are bound
  into one deterministic target fingerprint.
- API base and readiness URLs are separate, so an intentional root `404` cannot
  be mistaken for service unavailability.
- OCI deployments require `sha256:` digests. Render source deployments and
  Vercel static deployments explicitly use `not_applicable`; an invented image
  digest is rejected.
- Test credentials are environment references, and their values never enter
  output reports.
- Production DAST/fuzz/pentest requires a live approved window, source CIDRs,
  low request/concurrency caps, forbidden destructive operations, emergency stop
  contact and checksummed written authorization.
- Physical iOS and Android are probed automatically. An approved device cloud is
  accepted only when its credential environment variable exists.
- Render/Vercel and Kubernetes are distinct platform modes. Render production
  does not pretend to have a Kubernetes context.
- Disabled Redis requires an explicit, checksummed not-applicable decision.
- PostgreSQL, object storage, KMS, secondary-region, DNS/LB and telemetry access
  are capability checks, not inferred from local Docker or policy fixtures.
- Production, Security and Data Governance approvals must be real-name,
  timestamped, checksummed and bound to the exact target fingerprint.

Reports always retain `production_certification: false` and
`release_allowed: false`; the existing Batch 29-32 evidence controllers perform
the later independent certification decision after authorized executions finish.
