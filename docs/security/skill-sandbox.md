# Skill Sandbox Security

## Default policy

Untrusted Skills never load in the API process. The runtime requires an exact versioned adapter registration marked isolated, a verified non-revoked signature, passed security and compatibility reviews, an active installation, and an unexpired request. Network defaults to deny; filesystem and secret access default to none.

Effective permissions are the intersection of platform policy, publisher declaration, installation grant, and invocation context. Missing or unresolved permissions deny execution and cannot be inferred from functional need. Secrets are referenced by opaque `secretref:` identifiers and are not included in manifests, packages, provenance, logs, or execution responses.

UI extensions use only registered extension points. Third-party UI runs in an iframe with `allow-scripts` but without `allow-same-origin`; CSP starts at `default-src 'none'`. The host validates the exact frame window, HTTPS origin, protocol version, request identifier, and action allowlist for every message.

## Resource and content controls

- package: 10 MiB compressed, 50 MiB expanded, at most 1,000 regular files;
- no traversal, absolute paths, duplicate members, symlinks, encrypted ZIP members, or unchecked files;
- runtime deadline, cancellation, concurrency, output size, CPU, and memory configuration are bounded;
- egress is absent unless declared and independently allowed; private, loopback, link-local, and metadata destinations remain forbidden;
- input and output validate against closed JSON Schema objects.

## Failure response

A failed isolation or escape test disables the runtime class, quarantines affected versions and installations, cancels queued work, requests cancellation of running work, rotates exposed credentials, opens a critical incident, and blocks release. A signature or package finding additionally removes Marketplace listings and preserves the package checksum, key ID, audit trail, and appeal path.

## Evidence boundary

Unit and Compose integration tests cover policy code and execution state transitions. They do not prove host escape resistance. `sandbox-escape.json` from a controlled environment, bound to the release commit and artifact hash, is mandatory for production certification; without it the report remains `NOT_CERTIFIED`.
