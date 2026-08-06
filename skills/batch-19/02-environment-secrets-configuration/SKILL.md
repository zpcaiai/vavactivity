---
name: vav-environment-secrets-configuration
description: Operate strict typed configuration and redacted multi-provider secret resolution across development, test, CI, staging, production and DR.
---

Validate `config/env` before runtime and reject unknown fields or insecure production/DR settings. Resolve only `env://`, `file://`, Docker/Kubernetes, approved cloud, or SOPS references inside server workloads. Never emit values in logs, diffs, manifests, UI, evidence, or errors. Compare only redacted fingerprints with `make config-check` and `ENVIRONMENT=production make config-diff`; rotate leaked secrets and prove old versions fail.
