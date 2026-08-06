---
name: vav-disaster-recovery-chaos
description: Exercise scoped VAV infrastructure, provider, queue, release and data failures with explicit blast-radius controls and recovery evidence.
---

Chaos is local by default and requires the allowlisted service plus `CHAOS_CONFIRM=local-vav-compose-only`; validate the Compose project label before mutation. Test API/worker/scheduler exit, database/Redis/object/provider failure, queue backlog, bad flag/release, migration failure and corruption. Confirm business truth, payment pending state, AI safe degradation, notification durability, synchronous block denial and recovery slope. Follow runbooks and preserve reports; do not broaden the target or manufacture a DR PASS.
