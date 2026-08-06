# Experience quality runbook

1. Run migration 89 and `python -m vav.cli.seed_experience` after permissions.
2. Run `make experience-ia-check experience-route-check experience-dead-end-scan`.
3. Run backend and frontend tests, then user/admin E2E against the full stack.
4. Run `make experience-evidence-build`; inspect `build/experience/experience-evidence.json`.
5. Keep release blocked for any critical finding, broken notification route, unauthorized search result or stale task projection.

Do not manually correct domain state from this module. Repair the owning provider/event and rebuild projections. For a sensitive handoff or search leak, invalidate links/documents, remove unsafe projections, record the incident when required and rerun privacy/security gates.
