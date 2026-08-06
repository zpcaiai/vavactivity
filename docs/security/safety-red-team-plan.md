# Trust & Safety red-team release plan

Every run pins the application SHA, policy version, rule versions, model revisions, and a checksumed fixture manifest. A run is immutable after completion and must be approved by an administrator who neither started nor completed it.

Release-blocking groups:

1. Block bypass: direct profile URLs, old recommendation snapshots, activity participants, match and invitation history, relationship timelines, contact reveal tokens, browser caches, and admin projections.
2. Contact leakage: separated or Unicode digits, obfuscated email and messaging identifiers, QR/image metadata, stale grants, external links, and alternate API routes.
3. Harassment: post-decline, post-ending, block evasion, rate bursts, multi-target sequences, and reporter retaliation.
4. Fraud: money and gift-card requests, crypto/investment solicitation, emergency-loan narratives, off-platform payment, staff/mentor impersonation, account takeover, and duplicate content hashes.
5. Rule and model abuse: arbitrary code/SQL payloads, zero-width and confusable text, Base64-like text, multilingual mixing, prompt injection, fabricated system messages, and deterministic-rule override attempts.
6. Privacy and authority: cross-user report reads, reporter identity disclosure, evidence access without purpose, protected-attribute features, private counseling/AI scoring, fabricated evidence, conflict-of-interest review, and four-eyes bypass.

The release gate requires all of the following to equal zero: block bypasses, contact leaks, cross-user report access, reporter identity disclosures, fabricated user choice, rule DSL execution, restriction-cache leaks, missed critical routing, and high-impact approval bypasses. Any non-zero result stores the reproducible fixture and changes the run to `release_blocked`; it cannot be approved.

Automated classifiers are evaluated separately against a versioned, human-approved accuracy policy. A passing technical red-team run does not certify classifier quality, legal compliance, or production readiness by itself.
