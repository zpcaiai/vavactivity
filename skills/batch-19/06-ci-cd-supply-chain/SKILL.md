---
name: vav-ci-cd-supply-chain
description: Build VAV releases through locked quality gates, SBOM and vulnerability evidence, provenance, keyless signing and protected deployments.
---

PR gates validate manifests, dependencies, lint/format/type, tests, migration compatibility, contracts, secrets and sensitive-module security. Main adds full integration/E2E/red-team and images. Build four immutable images, emit CycloneDX SBOM/provenance, fail on critical/high policy findings, sign digests with workload identity, and bind all identities in a checksummed release manifest. Staging and production use protected workflows; missing scan, signature, backup, restore or human approval evidence blocks deployment.
