---
name: vav-skill-specification-sdk
description: Create or change canonical VAV Skill manifests, Python or TypeScript SDKs, test harnesses, scaffolding, or deterministic packages. Use whenever a Skill contract or SDK surface changes.
---

Define one immutable `skill.yaml` with SemVer, typed entrypoint, finite timeout, idempotency, capabilities, versioned dependencies, explicit data access, and deny-by-default resources. Derive SDK models from the canonical contract, reject extras, and build byte-identical archives from identical sources. Run `make skill-sdk-test skill-schema-test`.
