# Batch 10 implementation plan

Authority: supplied Batch 10 Hanna AI Agent specification and repository Skills.

1. Add encrypted, user-owned conversations, messages, turns, summaries, checkpoints,
   feedback, referrals and deletion controls.
2. Implement a pinned LangGraph `StateGraph` whose explicit nodes perform consent,
   independent risk screening, structured classification, completeness checks, RAG,
   controlled tools, response planning, citation validation, safety postcheck and persistence.
3. Keep inference separate from confirmed facts; require explicit opt-in for cross-turn memory.
4. Integrate only authorized Batch 9 retrieval and verify every source-backed claim before delivery.
5. Register code-owned tools with schemas, user scope, timeout, idempotency and confirmation for writes.
6. Query Activity, Course, Catalog, Entitlement and Counseling services through gateways and log
   bounded recommendations without inventing price, availability or outcomes.
7. Create idempotent ordinary/safety referrals and keep AI, human-advisor and system messages distinct.
8. Add immutable prompt releases, compatible model routes, deterministic local providers, budgets,
   fallback and per-turn version/cost/latency traces; reject fake providers in production.
9. Build consent-first user experiences and RBAC-gated AI operations, safety, release and evaluation views.
10. Seed at least 30 pinned evaluation cases and enforce zero unauthorized tools, cross-user access,
    privacy leakage, prompt/tool injection success and immediate-risk misses.
11. Add unit, integration, safety, concurrency and browser acceptance commands, followed by recursive
    Batch 1-9 regression.

Production memory retention, external model provider, regional emergency guidance and outbound human
referral policy remain undecided. Those paths stay fail closed and are not production-certified.
