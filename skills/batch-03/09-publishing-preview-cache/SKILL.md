---
name: vav-publishing-preview-cache
description: Implement review, scheduling, secure preview and cache invalidation.
---

Use scoped hash-only preview tokens, `X-Robots-Tag: noindex`, Celery Beat publication
and short-lived public caches. Publishing is a transaction; cache failure is
observable but must not corrupt publication state.
