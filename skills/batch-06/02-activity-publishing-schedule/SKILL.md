---
name: vav-activity-publishing-schedule
description: Implement reviewed VAV activity publication, registration windows, scheduled lifecycle jobs, cancellation and archive behavior. Use for activity editor, publishing, timing or cancellation work.
---

# Workflow

Validate ready localization, time ordering, timezone, format-specific location,
active ticket links, Catalog price/inventory and policy snapshots before
publication. Make scheduled transitions idempotent. Cancellation must stop new
sales and create downstream work; do not synchronously fan out Provider refunds.
