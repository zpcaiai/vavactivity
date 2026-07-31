# Promotion rules

`Promotion` defines an eligibility rule and benefit; `Coupon` is an optional
case-normalized credential for a coupon-required promotion. Public validation uses
one generic `COUPON_NOT_APPLICABLE` response to avoid coupon enumeration.

Rules can constrain products, SKUs, categories, currencies, subtotal, quantity,
first purchase and customer segment. Benefits support percentage basis points,
fixed minor-unit amounts and fixed prices. `FREE_ITEM` is reserved and rejected with
an explicit not-implemented error.

Evaluation is deterministic and honors exclusive, stackable and
automatic-only-stackable behavior. Quote evaluation does not increment redemption
counters. A separate internal reservation service locks promotion and coupon rows,
enforces global, per-user and budget limits, then confirms or releases the
redemption during the authoritative Batch 5 order transaction.
