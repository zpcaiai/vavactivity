---
name: vav-course-domain-model
description: Design or change VAV course, instructor, curriculum, enrollment, progress, assessment and certificate persistence. Use for any VAV course schema or migration work.
---

# Workflow

Model curriculum separately from Catalog and Commerce. Use explicit statuses,
UUID foreign keys, immutable version snapshots, append-only histories and
database uniqueness for idempotent projections. Preserve old enrollment
versions and private learner data.

