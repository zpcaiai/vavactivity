---
name: vav-batch-15-contact-exchange-consent
description: Implement separately confirmed, verified and revocable contact exchange.
---

# Rules

- Open exchange only after an accepted introduction and privacy opt-in by both members.
- Each member chooses only their own verified contact points or platform-only.
- One-sided consent reveals no contact selection or value.
- Bind grants to viewer, owner, contact IDs and value-hash snapshots.
- Mask list views; require a short-lived, viewer-bound, single-use token for plaintext.
- Revalidate verification and value hash both when issuing and redeeming a token.
- Withdrawal revokes future access and states honestly that copies outside the platform cannot be erased.

# Verify

Cover one-side consent, mutual activation, wrong viewer, stale value, token replay and revocation.
