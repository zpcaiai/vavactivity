# Environment configuration

The typed source of truth is `config/env/env.schema.json` plus the six YAML environments: development, test, CI, staging, production, and DR. Runtime variables map into `vav.core.config.Settings`; unknown structured keys fail validation.

Secrets are references (`env://`, `file://`, Docker/Kubernetes secret, SOPS, or approved cloud provider) and must never appear in config diffs, logs, front-end bundles, evidence, or manifests. Production/DR require debug off, secure cookies, explicit HTTPS origins, TLS data connections, private object storage, field encryption, and backup encryption.

Validate with `make config-check`; compare non-secret values with `ENVIRONMENT=production make config-diff`. Fingerprints deliberately separate non-secret configuration identity from a one-way secret-reference identity.
