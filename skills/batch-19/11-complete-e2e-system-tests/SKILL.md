---
name: vav-complete-e2e-system-tests
description: Run the 19-entry, 55-browser-test matrix covering complete Batches 1–18 user and operator journeys.
---

Run `make complete-e2e` against the fully migrated and seeded local test runtime. Use only synthetic users, deterministic fake payment/email/AI providers, fixed fixtures and polling helpers. Cover registration through service fulfillment, activities, courses, counseling, AI, notifications, dating profile, recommendation, mutual match/introduction/contact, relationship, membership, report/block, export/erasure and redacted admin/system operations. Assert idempotency, bilateral consent and zero block bypass; no real customer data or long blind sleeps.
