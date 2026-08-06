# Skill Marketplace Governance

## Publication policy

Marketplace is disabled unless explicitly configured. Public listing requires a verified active publisher, immutable signed package, SBOM and provenance, passed security and compatibility review, complete bilingual summary, support policy, complete data-use disclosure, automated review, and independent human approval. Pricing supports only free or private contract; automated billing and automatic public installation are forbidden.

Automated review rejects missing evidence, prohibited permissions, undisclosed reads/writes or external destinations, private-network egress, unsupported support terms, and incompatible or revoked versions. Automated success advances only to human review; it never publishes.

## Roles and separation

- Publisher owner/release manager: submit immutable versions and listings.
- Publisher verifier: verify publisher identity and key ownership; cannot be a publisher member.
- Security reviewer: review independent scan and compatibility evidence; cannot be the version submitter.
- Marketplace reviewer: approve or request changes; cannot be the listing submitter.
- Release manager: publish only an already-approved healthy listing.
- Enforcement reviewer: suspend/remove/quarantine/revoke with a reason code and audit evidence.
- Appeal reviewer: decide a pending appeal; cannot be a publisher member or the appeal submitter.

## Enforcement and appeals

Unsafe listings are unlisted immediately. Malicious or compromised packages additionally revoke signatures where appropriate, quarantine installed versions, stop new executions, cancel queued work, open an incident, and preserve rollback/uninstall guidance. Publisher appeal statements and decision reasons are encrypted. Accepted appeals return to human review rather than republishing automatically; rejected appeals remain suspended.

## Public evidence boundary

No listing is considered Marketplace verified from code tests alone. Real publisher identity verification, independent human review, signed artifact evidence, operational support confirmation, and production approval must be supplied to the certification tool for the exact Git commit. Missing evidence remains `NOT_EVALUATED` and release remains `NOT_CERTIFIED`.
