---
name: vav-payment-provider-abstraction
description: Build or extend VAV provider-neutral payment, cancellation, refund and Webhook boundaries. Use when adding payment providers or isolating Stripe and PayPal details from core Commerce.
---

# Workflow

Expose typed create, retrieve, cancel, refund and verify-Webhook operations.
Return provider-neutral redirect or limited client-secret actions. Pass only
VAV identifiers and non-sensitive metadata. Separate test and production
environments, enforce Provider idempotency and never return server secrets.
