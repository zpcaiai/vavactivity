---
name: vav-inventory-and-capacity
description: Implement finite inventory, service capacity and audited adjustments.
---

Calculate capacity minus reserved, sold and safety stock, with only configured
oversell allowance. Require reason, expected version and row lock for adjustments;
never reduce below committed quantity.
