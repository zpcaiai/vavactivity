# Membership Data Classification

| Data | Classification | Handling |
| --- | --- | --- |
| Plan/benefit public localization | public | Public API and caches allowed |
| Plan manifests, SKU mapping, quota policy | internal | Permission-gated admin access |
| Account, cycle, quota and usage IDs | confidential | Subject or scoped operator only |
| Subscription and Entitlement references | confidential | No payment-tool data in UI/events |
| Grant and adjustment reason text | sensitive | Encrypted; never emitted to outbox/logs |
| Audit safe metadata | internal | Stable IDs/codes only; append-only |

Membership events must not contain names, email, dating-profile fields, payment methods,
private grant reasons or security signals. Membership access cannot weaken privacy rights,
moderation, blocks or another person's hard criteria.
