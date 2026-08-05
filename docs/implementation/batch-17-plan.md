# Batch 17 Implementation Plan — Membership Entitlements and Atomic Quotas

Batch 17 implements membership as a versioned access-control projection. Catalog owns SKUs,
Commerce owns subscriptions and payment state, and Entitlement remains the paid-right source of
truth. Membership binds those authorities to plan versions, benefit grants and quota ledgers.

## Delivered architecture

| Concern | Owner |
| --- | --- |
| Products, prices, orders, payment and subscription truth | Batch 4/5 Commerce |
| Versioned plans, benefits, accounts, cycles, changes and quotas | Batch 17 `memberships` |
| Resource publication, safety, privacy, blocks and hard eligibility | Owning business module |
| Lifecycle scheduling, expiry, quota release and reconciliation | Worker membership tasks |

Migrations `0071`–`0076` enforce plan/version history, one effective paid account, one free
fallback, authoritative Subscription/Entitlement references, non-negative quota accounting,
idempotency and four-eyes grant/adjustment records.

## Request flows

1. A Commerce or Entitlement event enters the deduplicating membership inbox.
2. Projection reloads the authoritative Subscription, SKU mapping and Entitlement.
3. Only an active pair activates an account/cycle, grants benefits and allocates quota.
4. Access decisions check account, entitlement, plan version, benefit, scope and quota.
5. The owning module still checks publication, safety, blocks, capacity and other eligibility.
6. Quota-consuming work reserves first, then consumes delivered value or releases failed work.

## Operations

Member pages expose plans, effective membership, benefits, quota and explicit change preview.
Admin views are RBAC-gated and never expose payment-state forgery, safety bypass or direct
consumption overwrites. Plan authors cannot approve their own version; manual grant creators
cannot approve their own grant.

## Verification

`make membership-verify` is the Batch gate. CI additionally migrates a fresh pgvector database,
seeds the governed membership registry, runs full backend regression and applies migrations to
Neon only after Backend CI succeeds.
