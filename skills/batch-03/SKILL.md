---
name: vav-batch-03-public-site-cms-i18n-media
description: Implement the VAV public site, structured CMS, localization, media library, preview workflow, contact intake and administration framework.
---

# Goal

Deliver a responsive public site and backend-authoritative CMS for pages, articles,
consented testimonials, media, navigation, settings and contact intake.

# Required order

1. Read the manifest and `docs/implementation/batch-03-plan.md`.
2. Run `make auth-verify`.
3. Implement the skills in numeric order.
4. Preserve structured blocks, immutable versions and explicit publication states.
5. Keep unpublished, untranslated, private or unconsented material out of public APIs.
6. Finish with `make cms-verify`.

# Invariants

- Seeded copy remains draft and visibly unapproved.
- Testimonials require approved consent plus a consent record.
- Published updates create a new draft while the last public snapshot remains stable.
- Preview tokens are scoped, expiring and `noindex`.
- Media uploads use allowlisted MIME/size rules and reference-protected deletion.
- Locales use stable keys and intentional fallback with a visible signal.
