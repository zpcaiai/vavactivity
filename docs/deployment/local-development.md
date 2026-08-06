# Local development

## Prerequisites

Docker Compose v2, Node 22–26, pnpm 10.14, Python 3.12, uv 0.8, OpenSSL, curl, 4 GiB RAM, and 10 GiB free disk are required. Run `./scripts/vavctl doctor` before allocating containers.

## Bootstrap and operate

```bash
./scripts/vavctl bootstrap
./scripts/vavctl up
./scripts/vavctl smoke
```

Bootstrap creates only ignored local secrets, installs locked dependencies, builds images, upgrades the database, applies system/reference seeds, regenerates the API contract, and validates the manifest. Demo data is opt-in with `VAV_INCLUDE_DEMO=true` and is forbidden in production/DR.

Use `./scripts/vavctl down` to stop the runtime. Destructive volume removal requires `VAV_CONFIRM_RESET=delete-local-vav-data ./scripts/vavctl reset-local`.
