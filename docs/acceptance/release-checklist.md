# Release checklist

- [ ] Commit, OpenAPI, event manifest, configuration fingerprint, schema revision, and all image digests are bound in one release manifest.
- [ ] Dependencies are locked; SBOM, vulnerability scan, provenance, and keyless signatures are verified.
- [ ] Empty/snapshot migration gates, backfill plan, and rollback/forward-fix decision are approved.
- [ ] Unit, integration, concurrency, contract, frontend, complete E2E, privacy, payment, block-propagation, and red-team suites pass.
- [ ] Backup is current and an identified restore drill passes.
- [ ] Staging deploy, smoke, SLO observation, and capacity comparison pass.
- [ ] No critical vulnerability, unresolved secret leak, unsafe mutable image, or control-bypass flag exists.
- [ ] Production approver is independent and the change window/incident ownership are recorded.
- [ ] Production rollout and smoke pass; dashboards/alerts show stable recovery.
- [ ] Evidence is immutable and retained. Any missing item keeps the release `NOT_CERTIFIED`.
