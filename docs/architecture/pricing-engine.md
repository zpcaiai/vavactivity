# Pricing engine

All money uses integer minor units and a three-letter currency. Currency exponent is
stored in `supported_currencies`; TWD is seeded with exponent 0, while CNY, USD and
HKD use exponent 2. Cross-currency arithmetic fails with `CURRENCY_MISMATCH`.

Price resolution is deterministic:

1. retain only active SKU, product, price and price-book records inside their
   validity windows;
2. require an explicit price in the requested currency;
3. prefer price-book priority, exact region and exact customer segment;
4. prefer the latest `valid_from`;
5. fail with `PRICING_CONFIGURATION_CONFLICT` when two candidates remain
   indistinguishable.

Activated prices have no update endpoint. A change creates a new record referencing
`supersedes_price_id` and closes the old validity window. Quotes store algorithm
version, chosen price and price book, inputs, discounts and totals. Tax remains
`null` until a Batch 5 tax policy is approved.

Promotions use versioned rule and benefit schemas. Candidate ordering is priority,
code and UUID; percentage, fixed-amount and fixed-price discounts apply in that
order and cannot reduce a total below zero.
