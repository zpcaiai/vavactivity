---
name: vav-production-deployment
description: Deploy hardened immutable VAV releases through production Compose or Kubernetes with staged traffic and independent approval.
---

Require signed `@sha256` images, external state/secrets, TLS ingress, non-root/read-only containers, dropped capabilities, network policies, PDBs and autoscaling. Run migration before traffic and verify startup/readiness separately. Promote only a staging-tested release manifest through protected environments. Stop rollout on SLO or safety/privacy/payment regression; roll application digest back only when schema-compatible and preserve failed-release evidence.
