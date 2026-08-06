---
name: vav-batch-21-quality-governance
description: Implement or review VAV quality constitution, requirement and capability registries, traceability, closure matrices, gaps, risks, waivers, evidence, release gates, certification, and quality administration.
---

# Goal

Operate one fail-closed quality control plane across every VAV module. A named file is not proof: require current traceable evidence bound to a release, Git commit and environment.

# Required workflow

1. Read `quality-manifest.yaml`, `docs/quality/quality-constitution.md` and the relevant Batch 21 Skill.
2. Scan actual pages, OpenAPI operations, modules, migrations, events, permissions and tests; never infer a trace from similar names.
3. Register missing critical links as owned gaps and block certification until resolved.
4. Use only the declarative gate DSL; require independent approval and expiry for Waivers and certifications.
5. Run the scoped quality tests, then `make quality-verify acceptance skill-verify`.

# Evidence boundary

Keep production status `NOT_CERTIFIED` until real security, recovery, UAT and production approval evidence passes. Local architecture checks may be `PASS` without authorizing release.
