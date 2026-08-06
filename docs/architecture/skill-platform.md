# Skill Platform Architecture

## Scope

Batch 20 adds a governed extension plane without moving business authority out of the existing modules. A Skill may invoke only declared capabilities through the runtime; it cannot read databases, mint permissions, approve itself, or replace identity, privacy, payment, safety, and relationship rules.

## Components

- Canonical contracts live in `schemas/`, with Python, TypeScript, UI, test-kit, CLI, and IDE consumers checked for schema drift.
- The API `skills_platform` module is the persistent Registry, installation, execution, publisher, Marketplace, incident, and audit control plane.
- `services/skill-runtime` resolves immutable versions and enforces schemas, deadlines, cancellation, idempotency, permissions, capabilities, egress, secrets, and adapter isolation.
- Workers claim jobs with `FOR UPDATE SKIP LOCKED`; only an exact `(skill_name, semantic_version)` adapter allowlist may execute.
- Skill packages are deterministic ZIP artifacts stored privately by SHA-256. Registry ingestion revalidates paths, member checksums, manifest/schema identity, secret markers, Ed25519 signatures, SBOM, and provenance before persistence.
- Admin Web and the VS Code extension expose governed workflows. Neither can grant production permissions, sign official releases, or approve Marketplace listings.

## Trust transitions

```text
publisher pending -> independent verification -> verified
package upload -> signature verified/security pending -> independent security review
install plan -> approval when required -> validating -> active
listing submission -> automated review -> independent human review -> published
finding -> suspend/remove/quarantine/revoke -> incident -> independent appeal
```

The submitter cannot verify its publisher, security-review its version, human-review its listing, or decide its appeal. Installation and execution re-check current signature, revocation, trust, compatibility, permission, and lifecycle state; earlier approval is never treated as permanent authority.

## Data and observability

Execution input, configuration, output, private artifact references, revocation reasons, and appeal statements are encrypted. Default APIs expose presence and hashes, not sensitive payloads. Sensitive execution reads require a separate permission. Every lifecycle or enforcement transition produces an audit event; security enforcement also creates a durable incident.

## Deployment boundary

Official low-risk code may use reviewed in-process adapters. Third-party code requires an isolated runtime class. Production startup fails when signatures, SBOM/vulnerability/secret gates, human Marketplace review, approval separation, or sandbox defaults are weakened. Local green tests establish `tested`, not production certification.
