---
name: vav-batch-11-07-delivery-retry-deduplication
description: "Implement Delivery retry and deduplication for the VAV platform."
---

# Delivery retry and deduplication

Lock due work with `FOR UPDATE SKIP LOCKED`, keep one delivery per channel/dedup key, classify
temporary versus permanent failures, use bounded exponential backoff with jitter and create a
reviewable Dead Letter at final failure. Manual retry revalidates policy and cannot edit history.
