---
name: vav-stripe-payments
description: Implement VAV Stripe test or production-safe payment and subscription adapters, customer mapping and Stripe signature verification. Use for Stripe checkout, PaymentIntent, subscription or Webhook work.
---

# Workflow

Create Stripe objects on the server with stable idempotency keys and minimal
VAV metadata. Keep card data in Stripe. Pin the configured API version, isolate
environments and map Provider state into the neutral payment model. A return URL
only starts status polling; verified Stripe Webhooks decide payment success.
Without a configured test key, stay disabled rather than fabricating a remote
Stripe result.
