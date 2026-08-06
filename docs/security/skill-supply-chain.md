# Skill Supply Chain

## Release sequence

1. Validate canonical manifest and closed input/output/error schemas.
2. Run package tests and secret scan.
3. Build a deterministic `.vavskill` archive with per-member checksums.
4. Generate CycloneDX SBOM and in-toto/SLSA provenance bound to the package SHA-256.
5. Sign the exact archive with an active Ed25519 publisher key.
6. Upload package, signature envelope, SBOM, provenance, and schemas to Registry.
7. Registry independently repeats structural, checksum, secret, signature, SBOM, and provenance validation.
8. Store the content-addressed artifact privately and keep the version security status `pending`.
9. A different security reviewer records compatibility and scan evidence before the version becomes installable.

Publisher public keys are explicit trust roots; private keys never enter the application or provenance. The CLI reads access tokens only from process environment and never embeds credentials in packages. Immutable name/version pairs are serialized with advisory locks and cannot be overwritten.

## Revocation

Revocations may target a publisher key or one package checksum. Registry checks revocation at publication, installation planning, activation, and execution. Enforcement marks matching signatures revoked, quarantines versions and installations, cancels work, removes public listings, opens critical incidents, and preserves encrypted reasons plus non-secret evidence.

## Storage

Artifacts use a private S3-compatible bucket and content-addressed keys. Upload completion is accepted only after size and checksum metadata are read back. Database rows contain encrypted object references rather than public URLs. SBOM and provenance identities are encrypted and checksum-bound.

## Certification

Local deterministic build, tamper, signature, revocation, and Registry tests are required but insufficient. Production certification additionally requires commit-bound vulnerability/secret scan output, a signed release package, trusted publisher verification, restore evidence, and human approval.
