---
name: vav-paypal-payments
description: Implement VAV PayPal sandbox or production-safe order, capture, subscription and Webhook adapters. Use for PayPal approval redirects, captures or subscription billing.
---

# Workflow

Map VAV order ID to `custom_id` and order number to `invoice_id`. Before capture
or success processing, verify Provider ID, ownership, amount, currency,
environment and current state. Keep PayPal secrets server-side. A PayPal return
URL never confirms payment; poll VAV until a verified Webhook changes state.
