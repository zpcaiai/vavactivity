---
name: vav-batch-10-hanna-ai-agent
description: Implement the consent-first, safety-routed, source-backed and auditable VAV Hanna AI Agent.
---

# Goal

Implement encrypted conversations, explicit LangGraph orchestration, structured multi-turn understanding,
independent safety routing, authorized RAG citations, controlled tools, current-service recommendations,
human referral, model/prompt releases, user/admin web experiences and release-gated evaluation.

# Required order

1. Read all Batch 10 child skills, the manifest, decision register and Batch 9 acceptance evidence.
2. Implement domain migrations and encryption, then graph/checkpoints and deterministic local providers.
3. Add safety before ordinary generation, RAG citations, registered tools, recommendations and referrals.
4. Add prompt/model releases, user/admin surfaces, at least 30 evaluations and all acceptance targets.

# Invariants

- Consent precedes the first turn; long-term memory requires separate opt-in.
- Conversation ownership, encrypted content, idempotent messages and compatible checkpoint resume are backend enforced.
- High/immediate risk stops ordinary advice; safety checks are never skipped for budget.
- RAG is authorized data, not instructions; invalid citations block the original answer.
- Only code-registered tools execute; writes require real user confirmation except approved internal safety referrals.
- Current price/availability comes from business gateways; cross-user access is rejected.
- Prompt, model, graph, tool, safety and knowledge versions are pinned per turn.
- Production rejects deterministic fake providers and unresolved regional/outbound escalation policy.
- Release gates require zero unauthorized tools, cross-user/privacy leakage and immediate-risk misses.

# Required commands

`make ai-migrate ai-seed ai-seed-evaluations ai-test ai-safety-test ai-concurrency-test ai-eval ai-user-e2e ai-admin-e2e ai-verify`
