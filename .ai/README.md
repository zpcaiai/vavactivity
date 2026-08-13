# Shared AI workspace

This directory is the repository-local handoff point shared by Claude Code and
Codex.

- `TASK_PROGRESS.md` is the canonical task ledger and source of truth for AI
  handoffs.
- Keep repository instructions in `AGENTS.md` and `CLAUDE.md`; both point back
  to the same ledger so progress does not split across agent-specific files.
- Do not store secrets, credentials, raw production data, large logs, or build
  artifacts here.

When a task starts, read the ledger and compare it with the live Git state.
When a task reaches a milestone, is blocked, is handed off, or is completed,
update the ledger before the agent's final response.
