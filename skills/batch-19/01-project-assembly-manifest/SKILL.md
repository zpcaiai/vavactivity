---
name: vav-project-assembly-manifest
description: Validate the closed-world VAV application, service, module, migration, event, permission, seed, environment and API-contract assembly.
---

Treat `project-manifest.yaml` and the 19 `module.yaml` files as release contracts. Ensure every migration 1–83 has exactly one owner and a single head, every event has one versioned owner, every admin route maps to a registered permission, every seed is classified, six environments validate, and OpenAPI operation IDs are unique. Run `make manifest-check contract-test`; never accept an undocumented module, mutable contract, demo production seed, or reconstructed PASS.
