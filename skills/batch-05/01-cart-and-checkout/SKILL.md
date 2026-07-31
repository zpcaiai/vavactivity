---
name: vav-cart-and-checkout
description: Implement VAV server-side carts, anonymous cart ownership, cart merging, backend checkout previews and authoritative repricing. Use for cart, checkout preview or quote-consumption work.
---

# Workflow

Model active, checkout, converted, abandoned and expired carts with optimistic
versions. Authenticate ownership by user ID or an opaque anonymous-session ID.
Recalculate every item through the Catalog pricing engine immediately before
checkout. Reject stale prices, invalid coupons, unavailable inventory, purchase
limits and unsupported Provider currencies. Store only quote identifiers in
cart items; never accept a frontend total as authoritative.
