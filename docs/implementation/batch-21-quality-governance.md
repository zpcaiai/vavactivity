# Batch 21 implementation

Batch 21 adds migration `20260806_0087`, the `quality` API module, 33 exact permissions and four default quality roles, quality events, deterministic inventory and gap controls, a governed administrator console, 12 operational Skills, and fail-closed evidence/certification reporting.

Use `make quality-verify` for the complete local gate. It migrates and seeds the database, scans source artifacts, validates the manifest/trace/closure/gap contracts, runs unit/integration/gate/security tests, executes the administrator E2E, and builds a commit-bound technical report.

Seeded requirements and gates intentionally remain drafts. A trusted system import is not human approval; release managers must approve gate definitions independently before they can influence a release decision.
