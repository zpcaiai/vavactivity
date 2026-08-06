# Navigation and route model

`config/experience/routes.yaml` binds stable route, page and IA codes to authentication, permissions, capabilities, feature flags, prerequisites, fallback routes and help contexts.

The backend eligibility service is authoritative. Navigation caches must be scoped by identity, RBAC, capability, feature and restriction versions. Restricted members retain safe access to account security, privacy rights, safety status and appeals. Sensitive values are forbidden in query strings; entity identifiers are resolved again by the backend.

Every actionable notification must carry a registered target and fallback code. A changed or missing entity resolves to a safe status page, never a raw 404 or an unexplained home-page redirect.
