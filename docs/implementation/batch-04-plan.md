# Batch 4 implementation plan

Authority: the supplied Batch 4 catalog, pricing, inventory and promotion specification.

1. Add categories, products, validated SKUs and multilingual display content.
2. Add currency metadata, integer-minor-unit Money, price books and immutable effective prices.
3. Build deterministic quotes with fail-closed price conflict handling.
4. Add atomic inventory adjustment, reservation, confirmation and expiry.
5. Add versioned promotion rules, coupons and deterministic stacking.
6. Build public catalog and administration product-center pages.
7. Verify amounts, concurrency, information exposure and Batch 1–3 regression.

Tax, membership packaging and regional commercial policy remain configurable. Quotes never represent payment or entitlement.
