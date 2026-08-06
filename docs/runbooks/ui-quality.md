# UI Quality Runbook

1. Run `make ui-token-check ui-component-test ui-storybook-build ui-storybook-test`.
2. Run the three browser gates with `NO_PROXY=127.0.0.1,localhost` when a localhost proxy is configured.
3. Run `make ui-page-audit ui-admin-e2e ui-evidence-build`.
4. Inspect `build/ui/evidence-manifest.json`. Do not deploy while it says `NOT_CERTIFIED`.
5. Register accessibility and screenshot artifacts with checksums. Use a different reviewer to accept the audit and baseline records.
6. Release tokens only after all four evidence entries are accepted and checksum-bound.
